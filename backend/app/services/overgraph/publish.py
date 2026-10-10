"""Publish legal facts and frozen answers into the knowledge catalog."""

from dataclasses import dataclass, replace

from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.research import (
    QUESTION_TYPE,
    attach_question_dependency,
    mark_scope_index,
)
from app.services.overgraph.write import upsert_entity, upsert_text_unit, write_fact

ANSWER_PREDICATE = "research.answered_by"
ANSWER_TYPE = "research.answer"


@dataclass(frozen=True)
class AnswerPublish:
    question_id: str
    question_text: str
    scope: KnowledgeTenantScope
    identity: str
    evidence_set_id: str
    fact_id: str
    attributes: dict
    basis: list
    assessment: dict
    dependency_ids: tuple[str, ...]


def publish_legal_fact(
    catalog: Catalog,
    proposed: FactInput,
    *,
    fact_id: str,
    source: NodeInput,
    target: NodeInput,
    units: list[TextUnitWrite],
) -> str:
    source_row = upsert_entity(catalog, source)
    target_row = upsert_entity(catalog, target)
    for unit in units:
        upsert_text_unit(catalog, unit)
    write_fact(
        catalog,
        replace(proposed, source_id=source_row.key, target_id=target_row.key),
        key=fact_id,
    )
    mark_scope_index(catalog, proposed.scope.scope_key)
    return fact_id


def link_legal_questions(
    catalog: Catalog,
    *,
    fact_id: str,
    scope: KnowledgeTenantScope,
    questions: list[tuple[str, str]],
) -> None:
    for question_id, question_text in questions:
        attach_question_dependency(
            catalog,
            question_id=question_id,
            question_text=question_text,
            fact_id=fact_id,
            scope=scope,
        )


def publish_answer_fact(catalog: Catalog, published: AnswerPublish) -> str:
    source = upsert_entity(catalog, NodeInput(
        node_type=QUESTION_TYPE,
        name=published.question_text,
        scope=published.scope,
        identifier_namespace="research.question_id",
        identifier=published.question_id,
        attributes={"canonical_question_id": published.question_id},
    ))
    target = upsert_entity(catalog, NodeInput(
        node_type=ANSWER_TYPE,
        name=published.question_text,
        scope=published.scope,
        identifier_namespace="research.answer_id",
        identifier=published.identity,
        attributes={
            "basis": published.basis,
            "assessment": published.assessment,
            "evidence_set_id": published.evidence_set_id,
        },
    ))
    write_fact(
        catalog,
        FactInput(
            source_id=source.key,
            target_id=target.key,
            scope=published.scope,
            predicate=ANSWER_PREDICATE,
            fact_text=published.question_text,
            sources=(SourceRef("episode", published.evidence_set_id),),
            occurrence_key=published.identity,
            attributes=published.attributes,
        ),
        key=published.fact_id,
    )
    for ref in published.dependency_ids:
        attach_question_dependency(
            catalog,
            question_id=published.question_id,
            question_text=published.question_text,
            fact_id=ref,
            scope=published.scope,
        )
    catalog.sync()
    return published.fact_id
