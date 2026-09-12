"""WordAction materialization, persistence, and schema fail-closed rules."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text

from app.config import settings
from app.database.models import ExpertgranskningResult, Job, WordAction
from app.serializers import utcnow
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.word.actions import (
    SOURCE_TYPE_EXPERT_REVIEW_RESULT,
    persist_word_action,
    serialize_word_action,
)
from app.services.word.anchors import word_anchor_from_job_request
from app.services.word.materialize import (
    expert_review_word_action_spec,
    format_expert_review_comment_content,
    materialize_word_action,
)
from app.services.word.schemas import WordActionOut

_REQUEST = {
    "panel_id": 1,
    "customer_id": 1,
    "doc_id": "doc-actions",
    "word_session_id": "session-1",
    "sections": [
        {
            "heading": "Avtal",
            "heading_style": "Heading 1",
            "heading_paragraph_index": 0,
            "heading_unique_local_id": "h-0",
            "paragraphs": [
                {
                    "index": 1,
                    "text": "Detta stycke är tillräckligt långt.",
                    "style": "Normal",
                    "unique_local_id": "p-1",
                }
            ],
        }
    ],
}


def _result(**overrides) -> ExpertgranskningResult:
    values = {
        "id": "egr_1",
        "job_id": "job-1",
        "customer_id": 1,
        "section_index": 0,
        "paragraph_index": 1,
        "expert_id": "slot_1",
        "expert_namn": "Anna",
        "kommentar": "Skärp ingressen.",
        "is_heading_suggestion": False,
        "is_rewrite_suggestion": False,
        "foreslagen_text": None,
        "created_at": utcnow(),
    }
    values.update(overrides)
    return ExpertgranskningResult(**values)


def test_format_comment_preserves_word_visible_output():
    assert (
        format_expert_review_comment_content(
            kommentar="Skärp ingressen.",
            expert_namn="Anna",
            is_heading_suggestion=False,
        )
        == "Anna: Skärp ingressen."
    )
    assert (
        format_expert_review_comment_content(
            kommentar="Ny rubrik",
            expert_namn="",
            is_heading_suggestion=True,
        )
        == "Ny rubrik"
    )


def test_heading_stays_comment_even_if_foreslagen_text_exists():
    spec = expert_review_word_action_spec(
        _result(
            is_heading_suggestion=True,
            expert_namn="",
            kommentar="Ny rubrik",
            foreslagen_text="skulle kunna se ut som replace",
        )
    )
    assert spec is not None
    assert spec.action_type == "comment"
    assert spec.content == "Ny rubrik"
    assert spec.explanation is None


def test_rewrite_becomes_replace_with_rationale():
    spec = expert_review_word_action_spec(
        _result(
            is_rewrite_suggestion=True,
            expert_namn="",
            kommentar="Tydligare språk.",
            foreslagen_text="Ny formulering.",
        )
    )
    assert spec is not None
    assert spec.action_type == "replace"
    assert spec.content == "Ny formulering."
    assert spec.explanation == "Tydligare språk."


def test_rewrite_explanation_uses_same_visible_formatting_as_comments():
    spec = expert_review_word_action_spec(
        _result(
            is_rewrite_suggestion=True,
            expert_namn="Anna",
            kommentar="Tydligare språk.",
            foreslagen_text="Ny formulering.",
        )
    )
    assert spec is not None
    assert spec.action_type == "replace"
    assert spec.content == "Ny formulering."
    assert spec.explanation == "Anna: Tydligare språk."


def test_empty_content_is_not_materialized():
    assert expert_review_word_action_spec(_result(kommentar="  ")) is None
    assert (
        expert_review_word_action_spec(
            _result(is_rewrite_suggestion=True, foreslagen_text="  ", kommentar="x")
        )
        is None
    )


def test_unknown_action_type_fails_closed():
    with pytest.raises(ValidationError):
        WordActionOut(
            id="wa_1",
            job_id="job-1",
            action_type="insert",
            content="x",
            explanation=None,
            status="pending",
            source={"type": "expert_review_result", "id": "egr_1", "ordinal": 0},
            created_at="",
        )


def test_empty_content_fails_closed():
    with pytest.raises(ValidationError):
        WordActionOut(
            id="wa_1",
            job_id="job-1",
            action_type="comment",
            content="   ",
            explanation=None,
            status="pending",
            source={"type": "expert_review_result", "id": "egr_1", "ordinal": 0},
            created_at="",
        )


@pytest.mark.asyncio
async def test_materialize_persists_frozen_anchor_and_is_idempotent(client_db):
    _client, factory = client_db
    async with factory() as session:
        job = Job(
            id="job-materialize",
            customer_id=1,
            kind=WORD_JOB_KIND,
            status="running",
            label="Word actions",
            request=_REQUEST,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        first = _result(id="egr_a", job_id=job.id)
        second = _result(id="egr_b", job_id=job.id, kommentar="Annat.")
        session.add(job)
        session.add_all([first, second])
        await session.flush()
        action_a = await materialize_word_action(session, first, request=_REQUEST)
        again = await materialize_word_action(session, first, request=_REQUEST)
        action_b = await materialize_word_action(session, second, request=_REQUEST)
        third = await persist_word_action(
            session,
            customer_id=1,
            job_id=job.id,
            source_type=SOURCE_TYPE_EXPERT_REVIEW_RESULT,
            source_id=first.id,
            source_ordinal=1,
            action_type="comment",
            content="Andra åtgärden från samma källa.",
            explanation=None,
            anchor=word_anchor_from_job_request(_REQUEST, 1),
            created_at=utcnow(),
        )
        await session.commit()
        assert action_a is not None and again is not None and action_b is not None
        assert action_a.id == again.id
        assert action_a.id != action_b.id
        assert action_a.source_ordinal == 0
        assert third.source_ordinal == 1
        live = word_anchor_from_job_request(
            {
                **_REQUEST,
                "sections": [
                    {
                        **_REQUEST["sections"][0],
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "Ändrad live-text.",
                                "style": "Normal",
                                "unique_local_id": "p-1",
                            }
                        ],
                    }
                ],
            },
            1,
        )
        assert live is not None
        assert action_a.anchor["reviewed_text"] != live.reviewed_text
        out = serialize_word_action(action_a)
        assert out.anchor is not None
        assert out.anchor.reviewed_text == "Detta stycke är tillräckligt långt."
        assert out.action_type == "comment"
        assert out.content == "Anna: Skärp ingressen."
        rows = list(
            (
                await session.execute(
                    select(WordAction).where(WordAction.job_id == job.id)
                )
            ).scalars().all()
        )
        assert len(rows) == 3


def test_word_actions_migration_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "word_actions.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    command.upgrade(cfg, "069_word_actions")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        columns = {
            col["name"] for col in inspect(conn).get_columns("expertgranskning_results")
        }
        assert "status" not in columns
        conn.execute(
            text(
                "INSERT INTO kunder (name, slug, available_modules) "
                "VALUES ('Kund', 'kund-rt', '[]')"
            )
        )
        customer_id = conn.execute(
            text("SELECT id FROM kunder WHERE slug = 'kund-rt'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO jobs (id, customer_id, kind, status, label, request) "
                "VALUES ('job-rt', :customer_id, 'expertgranskning_word_review', "
                "'succeeded', 'RT', '{}')"
            ),
            {"customer_id": customer_id},
        )
        conn.execute(
            text(
                "INSERT INTO expertgranskning_results "
                "(id, job_id, customer_id, section_index, paragraph_index, "
                "expert_id, expert_namn, kommentar, is_heading_suggestion, "
                "is_rewrite_suggestion) "
                "VALUES ('egr-rt', 'job-rt', :customer_id, 0, 1, "
                "'slot_1', 'Anna', 'Text', 0, 0)"
            ),
            {"customer_id": customer_id},
        )

    command.downgrade(cfg, "068_word_application_lifecycle")
    with engine.begin() as conn:
        status_col = next(
            col
            for col in inspect(conn).get_columns("expertgranskning_results")
            if col["name"] == "status"
        )
        assert status_col["nullable"] is False
        assert (
            conn.execute(
                text("SELECT status FROM expertgranskning_results WHERE id = 'egr-rt'")
            ).scalar_one()
            == "pending"
        )
        assert "word_actions" not in inspect(conn).get_table_names()

    command.upgrade(cfg, "069_word_actions")
    with engine.begin() as conn:
        columns = {
            col["name"] for col in inspect(conn).get_columns("expertgranskning_results")
        }
        assert "status" not in columns
        assert "word_actions" in inspect(conn).get_table_names()
        assert (
            conn.execute(
                text("SELECT id FROM expertgranskning_results WHERE id = 'egr-rt'")
            ).scalar_one()
            == "egr-rt"
        )
