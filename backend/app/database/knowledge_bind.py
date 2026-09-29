"""Register knowledge-scope listeners after models are defined."""

from app.database.knowledge_observation import KnowledgeObservationRecord
from app.database.knowledge_scope import bind_scoped_mapper
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeEntityRecord,
    KnowledgeGraphEventRecord,
    KnowledgeQuestionRow,
    KnowledgeRelationshipRecord,
    TextUnitRecord,
)


def register_knowledge_scope_listeners() -> None:
    for model in (
        CanonicalDocumentRecord,
        DocumentVersionRecord,
        DocumentSectionRecord,
        TextUnitRecord,
        KnowledgeClaimRecord,
        KnowledgeClaimAnswer,
        KnowledgeEntityRecord,
        KnowledgeRelationshipRecord,
        KnowledgeGraphEventRecord,
        KnowledgeObservationRecord,
        KnowledgeQuestionRow,
    ):
        bind_scoped_mapper(model)
