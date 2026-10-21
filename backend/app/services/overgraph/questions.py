"""Canonical question nodes in OverGraph.

The SQL ``knowledge_questions`` row keeps the question identity as application data; the
graph node is the anchor retrieval uses. Writing it here replaces the retired SQL
``graph_v2.questions.question_node`` call.
"""

from __future__ import annotations

import asyncio

from app.services.overgraph.answers import QUESTION_NS, QUESTION_TYPE
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.write import upsert_entity
from app.services.graph_v2.types import NodeInput


def upsert_question_entity(*, question_id: str, display_text: str, scope) -> GraphRecord:
    return upsert_entity(require_knowledge(), NodeInput(
        node_type=QUESTION_TYPE,
        name=display_text,
        scope=scope,
        identifier_namespace=QUESTION_NS,
        identifier=question_id,
        attributes={"canonical_question_id": question_id},
    ))


async def ensure_question_node(*, question_id: str, display_text: str, scope) -> GraphRecord:
    """Async wrapper so call sites can stay on the session-based signature."""
    return await asyncio.to_thread(
        upsert_question_entity,
        question_id=question_id,
        display_text=display_text,
        scope=scope,
    )
