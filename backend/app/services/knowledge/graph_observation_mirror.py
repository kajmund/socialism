"""Transitional mirror: legacy research observations also become graph observation nodes.

A research observation records what the pipeline noticed (source quality, gaps, failed
verification). It carries **no Jev verdict**, so it can never verify a claim and never
creates a ``CONTRADICTS`` edge — it is inventory, not knowledge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.claims import (
    VerificationObservationWrite,
    upsert_verification_observation,
)

if TYPE_CHECKING:
    from app.services.knowledge.observations import KnowledgeObservation

TAXONOMY_VERSION = "research-observation-v1"


def mirror_observation(observation: KnowledgeObservation) -> str:
    node = upsert_verification_observation(
        require_knowledge(),
        VerificationObservationWrite(
            class_id=observation.observation_class,
            document_id=observation.document_id,
            document_version_id=observation.document_version_id,
            value={
                "statement": observation.statement_normalized,
                "question_key": observation.question_key,
            },
            polarity="observed",
            taxonomy_version=TAXONOMY_VERSION,
            scope=observation.scope,
            kind=observation.kind,
            decision=None,
        ),
        key=observation.id,
    )
    return node.key
