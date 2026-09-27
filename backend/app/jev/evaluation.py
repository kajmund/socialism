"""Content-addressed JEV evaluation identity.

A result may be reused only when the semantic input, the evaluator
definition, and the security scope are identical. Object ids are not an
evaluation key: the same claim or document can change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

JEV_PROVIDER = "jev"

EVALUATOR_GRAPH_REVALIDATION = "graph_relation_revalidation"
EVALUATOR_GRAPH_REVALIDATION_VERSION = "v1"
EVALUATOR_GRAPH_REVALIDATION_POLICY = "v1"

EVALUATOR_RESEARCH_ASSESSMENT = "research_assessment"
EVALUATOR_RESEARCH_COMPLETENESS = "research_completeness"
EVALUATOR_EVIDENCE_SCREEN = "evidence_screen"
EVALUATOR_QUESTION_STRUCTURE = "research_question_structure"
EVALUATOR_DECOMPOSITION_VALIDATION = "research_decomposition_validation"
EVALUATOR_CHILD_REDUNDANCY = "research_child_redundancy"
EVALUATOR_SYNTHESIS_READINESS = "research_synthesis_readiness"
EVALUATOR_QUESTION_COMPLETENESS = "research_question_completeness"
EVALUATOR_PASSAGE_RELEVANCE = "passage_relevance"
EVALUATOR_VERSION_V1 = "v1"
EVALUATION_POLICY_V1 = "v1"

EVALUATION_STATUS_VALID = "valid"


@dataclass(frozen=True)
class EvaluationRequest:
    """One deterministic evaluation. The key is a hash of every field."""

    evaluator_id: str
    evaluator_version: str
    model_provider: str
    model: str
    model_config: Mapping[str, Any]
    questions: Mapping[str, Any]
    state: Mapping[str, Any]
    content_hashes: Mapping[str, str]
    policy_version: str
    security_scope: str
    domain_context_version: str | None = None


@dataclass(frozen=True)
class EvaluationArtifact:
    """Immutable successful evaluation. Failures are never stored."""

    evaluation_key: str
    security_scope: str
    result: Mapping[str, Any]
    signals: Mapping[str, float]
    evaluator_id: str
    evaluator_version: str
    model_provider: str
    model: str
    input_provenance: Mapping[str, Any]
    created_at: datetime
    status: str


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def evaluation_material(request: EvaluationRequest) -> dict[str, Any]:
    return {
        "content_hashes": dict(request.content_hashes),
        "domain_context_version": request.domain_context_version,
        "evaluator_id": request.evaluator_id,
        "evaluator_version": request.evaluator_version,
        "model": request.model,
        "model_config": dict(request.model_config),
        "model_provider": request.model_provider,
        "policy_version": request.policy_version,
        "questions": dict(request.questions),
        "security_scope": request.security_scope,
        "state": dict(request.state),
    }


def evaluation_key(request: EvaluationRequest) -> str:
    if not request.security_scope.strip():
        raise ValueError("evaluation security_scope is required")
    return sha256_text(canonical_json(evaluation_material(request)))


def artifact_id(security_scope: str, key: str) -> str:
    return sha256_text(f"{security_scope}\0{key}")


def threshold_config(**values: float) -> dict[str, str]:
    """Stable config fragment. A threshold change must miss the previous key."""
    return {name: format(value, ".6f") for name, value in sorted(values.items())}
