"""Legal adapter: structured facts link source/context subjects to reusable values."""

import json
from collections.abc import Sequence


from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import NodeInput
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.scope import KnowledgeTenantScope


def _source_entity(entities: Sequence[KnowledgeEntity]) -> KnowledgeEntity:
    source = next((entity for entity in entities if entity.entity_type == "legal.source"), None)
    if source is None:
        raise PermanentGraphError("legal graph projection payload has no source entity")
    return source




def _fact_text(source_name: str, claim: KnowledgeClaim) -> str:
    value = claim.value.get("value", claim.value)
    detail = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    return f"{source_name} — {claim.predicate}: {detail}"


def value_node_input(claim: KnowledgeClaim, scope: KnowledgeTenantScope) -> NodeInput:
    """A typed value is reusable across sources; source identity stays on the fact edge."""
    value = claim.value.get("value", claim.value)
    if claim.predicate == "legal.adjustment_granted" and isinstance(value, bool):
        name = "Adjustment granted" if value else "No adjustment"
    elif isinstance(value, str):
        name = value.replace("_", " ").strip()
    else:
        name = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return NodeInput(
        node_type=f"{claim.predicate}.value",
        name=name,
        scope=scope,
        attributes={"value": value},
    )
