"""Stable stage-level failure categories, shared by providers, logs and evaluations."""

from typing import Literal

FailureCategory = Literal[
    "search_no_hit",
    "passage_not_found",
    "resolve_no_document",
    "fetch_failed",
    "domain_schema_invalid",
    "citation_grounding_failed",
    "irrelevant_relation",
    "unsupported_source_shape",
    "selection_failed",
    "budget_exhausted",
    "question_incoherent",
]
