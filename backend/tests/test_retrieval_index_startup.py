"""The derived lexical index is opened/built/reconciled without a manual CLI."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.services import retrieval_index
from app.services.graph_v2.types import FactInput, NodeInput
from app.services.knowledge.scope import customer_scope
from app.main import _open_retrieval_index
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.write import upsert_entity, write_fact

CUSTOMER = 1


def _entity(key: str) -> str:
    return upsert_entity(
        require_knowledge(),
        NodeInput(node_type="core.concept", name=key, scope=customer_scope(CUSTOMER)),
    ).key


def _fact(*, fact_id: str, text: str) -> None:
    left, right = _entity(f"{fact_id}-subject"), _entity(f"{fact_id}-object")
    write_fact(
        require_knowledge(),
        FactInput(
            source_id=left,
            target_id=right,
            scope=customer_scope(CUSTOMER),
            predicate="legal.rule",
            fact_text=text,
            sources=(),
        ),
        key=fact_id,
    )


@pytest.fixture
def index_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "lexical"
    monkeypatch.setattr(retrieval_index, "index_directory", lambda: target)
    retrieval_index.set_index(None, target)
    yield target
    retrieval_index.set_index(None)


def test_require_current_index_builds_a_missing_index_from_graph(index_dir: Path) -> None:
    _fact(fact_id="startup-fact", text="Lexikalt index byggs vid start")

    index = retrieval_index.require_current_index()

    assert retrieval_index.get_index() is index
    assert [hit.key for hit in index.search_fact_keys(
        "index", tenant_ids=(f"customer:{CUSTOMER}",),
    )]


def test_require_current_index_reconciles_graph_writes(index_dir: Path) -> None:
    _fact(fact_id="first", text="Första faktan om avtalsvillkor")
    first = retrieval_index.require_current_index()
    assert [hit.key for hit in first.search_fact_keys(
        "avtalsvillkor", tenant_ids=(f"customer:{CUSTOMER}",),
    )] == ["first"]

    time.sleep(0.003)
    _fact(fact_id="second", text="Andra faktan om uppsägning")
    index = retrieval_index.require_current_index()

    assert [hit.key for hit in index.search_fact_keys(
        "uppsägning", tenant_ids=(f"customer:{CUSTOMER}",),
    )] == ["second"]


def test_ensure_current_defers_an_empty_graph_without_crashing(
    index_dir: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    assert retrieval_index.ensure_current() is None
    with pytest.raises(
        retrieval_index.RetrievalIndexUnavailableError, match="graph is empty",
    ):
        retrieval_index.require_current_index()
    assert "lexical index deferred" in caplog.text


def test_version_mismatch_is_rebuilt_from_graph(index_dir: Path) -> None:
    _fact(fact_id="versioned", text="Indexversion ska byggas om")
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "version.json").write_text('{"version": "old"}', encoding="utf-8")

    index = retrieval_index.require_current_index()

    assert [hit.key for hit in index.search_fact_keys(
        "indexversion", tenant_ids=(f"customer:{CUSTOMER}",),
    )] == ["versioned"]


@pytest.mark.asyncio
async def test_lifespan_helper_runs_ensure_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.main.retrieval_index.ensure_current", lambda: calls.append(True),
    )
    await _open_retrieval_index()
    assert calls == [True]
