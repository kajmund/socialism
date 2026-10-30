"""Exercise the deployed Alembic marker alongside the Graph v2 branch."""

import sqlite3
import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_deployed_research_marker_upgrades_without_replaying_claim_migrations(
    tmp_path: Path, monkeypatch,
) -> None:
    db = tmp_path / "deployed.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    app_logger = logging.getLogger("app.research.observability")

    command.upgrade(config, "126_knowledge_claim_source_independence")
    assert not app_logger.disabled
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TABLE knowledge_answer_reviews")
        connection.execute("CREATE TABLE research_question_nodes (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO research_question_nodes VALUES ('preserved')")
        connection.execute(
            "UPDATE alembic_version SET version_num = ?",
            ("136_revalidation_evaluation_key",),
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert not app_logger.disabled
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (ScriptDirectory.from_config(config).get_current_head(),)
        ]
        assert connection.execute("SELECT id FROM research_question_nodes").fetchall() == [
            ("preserved",)
        ]
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "graph_ingest_work", "knowledge_answer_reviews", "graph_embedding_cache",
        } <= names
        # The SQL graph mirror is dropped at head; orchestr/audit tables stay.
        assert "graph_nodes" not in names
        assert "graph_facts" not in names
        assert "graph_fact_question_dependencies" not in names
        assert "text_units" not in names
        assert "shared_text_chunks" not in names
        assert "graph_fact_revalidations" not in names
        assert "graph_question_revalidation_work" not in names


def _table_names(db: Path) -> set[str]:
    with sqlite3.connect(db) as connection:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def test_head_drops_unused_graph_revalidation_queues(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "revalidation-drop.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "e8c2f4a1b6d0")
    before = _table_names(db)
    assert {
        "graph_fact_revalidations",
        "graph_question_revalidation_work",
        "graph_fact_question_dependencies",
        "graph_ingest_work",
        "knowledge_answer_reviews",
        "evidence_set_revalidations",
    } <= before

    command.upgrade(config, "head")
    after = _table_names(db)
    assert "graph_fact_revalidations" not in after
    assert "graph_question_revalidation_work" not in after
    assert "evidence_set_revalidations" not in after
    assert {
        "graph_ingest_work",
        "knowledge_answer_reviews",
    } <= after
    assert "graph_fact_question_dependencies" not in after
    assert ScriptDirectory.from_config(config).get_current_head() == (
        "196_gliner_runtime_span_fields"
    )
    assert {
        "tabular_reviews",
        "tabular_review_columns",
        "tabular_review_rows",
        "tabular_review_cells",
    } <= after


def test_existing_text_units_are_preserved_when_the_sql_mirror_is_dropped(
    tmp_path: Path, monkeypatch,
) -> None:
    """A dev database that still carries the retired mirror must upgrade, not abort."""
    db = tmp_path / "dev-with-units.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "190_drop_evidence_set_revalidations")
    digest = "a" * 64
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO shared_text_chunks (content_hash, text) VALUES (?, ?)",
            (digest, "Paragraf 12."),
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(text_units)")
        }
        payload = {
            "id": "unit-1",
            "scope_type": "customer",
            "scope_key": "customer:1",
            "customer_id": 1,
            "document_version_id": "ver-1",
            "document_id": "doc-1",
            "section_id": None,
            "ordinal": 0,
            "content_hash": digest,
            "locator": "p1",
            "page_start": None,
            "page_end": None,
            "char_start": 0,
            "char_end": 11,
            "valid_from": None,
            "valid_to": None,
            "embedding_id": "unit-1",
            "extra": "{}",
        }
        selected = {key: value for key, value in payload.items() if key in columns}
        connection.execute(
            f"INSERT INTO text_units ({', '.join(selected)}) "
            f"VALUES ({', '.join('?' for _ in selected)})",
            tuple(selected.values()),
        )
    command.upgrade(config, "head")
    with sqlite3.connect(db) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "text_units" not in names
        assert "shared_text_chunks" not in names
        assert "text_units_dropped" in names
        assert "shared_text_chunks_dropped" in names
        assert connection.execute(
            "SELECT id, content_hash FROM text_units_dropped"
        ).fetchall() == [("unit-1", digest)]
        assert connection.execute(
            "SELECT text FROM shared_text_chunks_dropped"
        ).fetchall() == [("Paragraf 12.",)]


def test_fresh_database_upgrades_to_head_without_a_parity_approval(
    tmp_path: Path, monkeypatch,
) -> None:
    """An empty mirror has nothing to preserve; the parity gate compares SQL data.

    The graph tables are created in the same uncommitted migration transaction, so a
    fresh database must not open a second connection to parity-check them.
    """
    db = tmp_path / "fresh.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "head")

    names = _table_names(db)
    assert "text_units" not in names
    assert "shared_text_chunks" not in names
    assert "graph_facts" not in names
    assert "knowledge_claims" not in names
    assert {"graph_ingest_work", "knowledge_answer_reviews", "graph_embedding_cache"} <= names
    assert ScriptDirectory.from_config(config).get_current_head() == "196_gliner_runtime_span_fields"
    assert {"tabular_reviews", "tabular_review_columns", "tabular_review_cells"} <= names


def test_upgrade_refuses_to_drop_the_mirror_when_sql_has_rows(
    tmp_path: Path, monkeypatch,
) -> None:
    db = tmp_path / "parity.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "190_drop_evidence_set_revalidations")
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO knowledge_entities "
            "(id, customer_id, entity_type, entity_key, name, extra, created_at, "
            "scope_type, scope_key) "
            "VALUES ('e1', 1, 'legal.source', 'k1', 'Avtalslagen', '{}', "
            "'2026-01-01 00:00:00', 'customer', 'customer:1')"
        )

    with pytest.raises(Exception, match="parity"):
        command.upgrade(config, "head")

    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("190_drop_evidence_set_revalidations",),
        ]
        names = _table_names(db)
        assert {"knowledge_entities", "knowledge_claims", "text_units"} <= names
