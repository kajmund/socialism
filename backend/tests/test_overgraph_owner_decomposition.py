"""Question decomposition is written through the owner as one mutation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.graph_v2.questions import link_decomposition
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import DEPENDS_ON, FACT, SUBJECT, SUPPORTS
from app.services.overgraph.owner_runtime import get_owner_runtime


def _question(question_id: str, text: str):
    return SimpleNamespace(
        id=question_id,
        display_text=text,
        scope_type="customer",
        customer_id=1,
        scope_key="customer:1",
    )


async def test_decomposition_uses_one_owner_mutation(monkeypatch):
    from app.services.overgraph import write as direct_write

    def fail_direct(*_args, **_kwargs):
        raise AssertionError("decomposition must not use the direct fact writer")

    monkeypatch.setattr(direct_write, "write_fact", fail_direct)
    client = get_owner_runtime().require_client()
    before = (await client.health())["metrics"]
    await link_decomposition(
        None,
        _question("parent-1", "Vad gäller uppsägningstiden?"),
        _question("child-1", "Gäller det även provanställning?"),
    )
    after = (await client.health())["metrics"]
    assert after["applied"] - before["applied"] == 1

    catalog = require_knowledge()
    facts, _ = catalog.query_nodes(
        label_filter={"labels": [FACT], "mode": "all"}, limit=10,
    )
    fact = next(
        row for row in facts
        if row.props.get("predicate") == "research.decomposed_to"
    )
    assert json.loads(fact.props["source_refs_json"]) == [
        {"kind": "episode", "ref": "parent-1"},
    ]
    parent = catalog.get_by_key("Entity", fact.props["source_key"])
    child = catalog.get_by_key("Entity", fact.props["target_key"])
    assert parent is not None and child is not None
    assert parent.engine_id is not None and child.engine_id is not None
    assert fact.engine_id is not None
    assert catalog.get_edge_by_triple(fact.engine_id, parent.engine_id, SUBJECT)
    assert catalog.get_edge_by_triple(parent.engine_id, fact.engine_id, DEPENDS_ON)
    episode = catalog.get_by_key("Entity", "episode:parent-1")
    assert episode is not None and episode.engine_id is not None
    assert catalog.get_edge_by_triple(episode.engine_id, fact.engine_id, SUPPORTS)


@pytest.mark.parametrize(
    ("parent", "child"),
    [
        (None, _question("child-1", "barn")),
        (_question("parent-1", "förälder"), None),
    ],
)
async def test_decomposition_requires_both_questions(parent, child):
    from app.services.graph_v2.errors import PermanentGraphError

    with pytest.raises(PermanentGraphError):
        await link_decomposition(None, parent, child)
