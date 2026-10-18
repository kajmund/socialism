"""Exact-reuse identity. Normalization is not a legal interpretation."""

from __future__ import annotations

import hashlib

from app.services.document_qa.types import AnalysisContract


def normalize_question(text: str) -> str:
    return " ".join(text.casefold().split())


def reuse_digest(normalized: str, version_id: str, contract: AnalysisContract) -> str:
    payload = "\n".join(
        (
            normalized,
            version_id,
            contract.kind,
            contract.method,
            contract.model,
            contract.model_version,
            contract.examined_scope,
            normalize_question(contract.question_context),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def question_key(customer_id: int, digest: str) -> str:
    return f"qa:q:{customer_id}:{digest}"


def short_digest(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def answer_key(customer_id: int, digest: str, created_at: str, text: str) -> str:
    return f"qa:a:{customer_id}:{short_digest(digest, created_at, text)}"


def post_key(customer_id: int, answer: str, ordinal: int) -> str:
    return f"qa:p:{customer_id}:{short_digest(answer, str(ordinal))}"


def review_key(customer_id: int, answer: str, reviewed_at: str, action: str) -> str:
    return f"qa:r:{customer_id}:{short_digest(answer, reviewed_at, action)}"
