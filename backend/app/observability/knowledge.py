"""Knowledge persist counters. Never log document text."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from app.observability.events import log_event

logger = logging.getLogger("app.knowledge.observability")

EVENT_DATASET_KNOWLEDGE = "socialism.knowledge"
EVENT_KNOWLEDGE_PERSIST = "knowledge.persist.decision"
EVENT_KNOWLEDGE_REJECTED = "knowledge.persist.rejected"

KnowledgeKind = Literal["claim", "entity", "relationship", "observation"]
KnowledgeAction = Literal[
    "proposed",
    "accepted",
    "reused",
    "rejected_by_class",
    "merged",
]


@dataclass
class KnowledgePersistStats:
    claims_proposed: int = 0
    claims_accepted: int = 0
    claims_reused: int = 0
    claims_rejected_by_class: int = 0
    claims_merged: int = 0
    entities_proposed: int = 0
    entities_accepted: int = 0
    entities_reused: int = 0
    relationships_proposed: int = 0
    relationships_accepted: int = 0
    relationships_reused: int = 0
    observations_accepted: int = 0
    observations_reused: int = 0
    _events: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "claims_proposed": self.claims_proposed,
            "claims_accepted": self.claims_accepted,
            "claims_reused": self.claims_reused,
            "claims_rejected_by_class": self.claims_rejected_by_class,
            "claims_merged": self.claims_merged,
            "entities_proposed": self.entities_proposed,
            "entities_accepted": self.entities_accepted,
            "entities_reused": self.entities_reused,
            "relationships_proposed": self.relationships_proposed,
            "relationships_accepted": self.relationships_accepted,
            "relationships_reused": self.relationships_reused,
            "observations_accepted": self.observations_accepted,
            "observations_reused": self.observations_reused,
        }


def record_knowledge_decision(
    stats: KnowledgePersistStats,
    *,
    kind: KnowledgeKind,
    action: KnowledgeAction,
    persistence_class: str | None = None,
    reason: str | None = None,
    predicate: str | None = None,
    identity_key: str | None = None,
    document_id: str | None = None,
    relation: str | None = None,
    entity_type: str | None = None,
) -> None:
    _increment(stats, kind, action)
    fields: dict[str, object] = {
        "knowledge_kind": kind,
        "action": action,
    }
    if persistence_class:
        fields["persistence_class"] = persistence_class
    if reason:
        fields["reason"] = reason
    if predicate:
        fields["predicate"] = predicate
    if identity_key:
        fields["identity_key"] = identity_key
    if document_id:
        fields["document_id"] = document_id
    if relation:
        fields["relation"] = relation
    if entity_type:
        fields["entity_type"] = entity_type
    stats._events.append(fields)
    outcome = "success" if action != "rejected_by_class" else "rejected"
    event_name = (
        EVENT_KNOWLEDGE_REJECTED if action == "rejected_by_class" else EVENT_KNOWLEDGE_PERSIST
    )
    log_event(
        logger,
        event_name,
        dataset=EVENT_DATASET_KNOWLEDGE,
        outcome=outcome,
        fields={"knowledge": fields},
    )


def _increment(
    stats: KnowledgePersistStats,
    kind: KnowledgeKind,
    action: KnowledgeAction,
) -> None:
    key = f"{kind}s_{action}"
    if kind == "observation" and action == "rejected_by_class":
        return
    if not hasattr(stats, key):
        return
    setattr(stats, key, int(getattr(stats, key)) + 1)
