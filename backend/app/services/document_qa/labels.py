"""Q&A labels for a tenant OverGraph. Production Fact search does not use these."""

from app.services.overgraph.labels import CONTAINS, DOCUMENT_VERSION, TEXT_UNIT

CANONICAL_DOCUMENT = "CanonicalDocument"
QUESTION = "Question"
ANSWER = "Answer"
ANSWER_POST = "AnswerPost"
REVIEW_EVENT = "ReviewEvent"

HAS_VERSION = "HAS_VERSION"
HAS_QUESTION = "HAS_QUESTION"
ABOUT_VERSION = "ABOUT_VERSION"
HAS_ANSWER = "HAS_ANSWER"
HAS_POST = "HAS_POST"
CITES = "CITES"
HAS_REVIEW = "HAS_REVIEW"

__all__ = [
    "ANSWER",
    "ANSWER_POST",
    "ABOUT_VERSION",
    "CANONICAL_DOCUMENT",
    "CITES",
    "CONTAINS",
    "DOCUMENT_VERSION",
    "HAS_ANSWER",
    "HAS_POST",
    "HAS_QUESTION",
    "HAS_REVIEW",
    "HAS_VERSION",
    "QUESTION",
    "REVIEW_EVENT",
    "TEXT_UNIT",
]
