"""Canonical question nodes in OverGraph.

The SQL ``knowledge_questions`` row keeps the question identity as application data; the
graph node is the anchor retrieval uses. Writing it here replaces the retired SQL
``graph_v2.questions.question_node`` call.
"""

from __future__ import annotations

from app.services.graph_v2.types import NodeInput
from app.services.overgraph.answers import QUESTION_NS, QUESTION_TYPE
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.owner_graph import apply_batch
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.write import entity_nodes


async def ensure_question_node(*, question_id: str, display_text: str, scope) -> GraphRecord:
    """Anchor the question in the knowledge catalog through the Owner."""
    owner = get_owner_runtime().require_client()
    key, nodes = entity_nodes(NodeInput(
        node_type=QUESTION_TYPE,
        name=display_text,
        scope=scope,
        identifier_namespace=QUESTION_NS,
        identifier=question_id,
        attributes={"canonical_question_id": question_id},
    ))
    await apply_batch(owner, "research:question", nodes=[
        {"labels": list(node["labels"]), "key": node["key"], "props": dict(node["props"])}
        for node in nodes
    ], edges=[])
    response = await owner.read([{"label": "Entity", "key": key}])
    return GraphRecord(
        key=key, labels=("Entity",),
        props=dict(response["values"].get(f"Entity:{key}") or {}),
        engine_id=response["ids"].get(f"Entity:{key}"),
    )
