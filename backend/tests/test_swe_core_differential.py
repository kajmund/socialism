"""Differential tests: Rust is the only implementation of the semantics.

B2's acceptance criteria require that the same input produces identical
outcomes whether it is evaluated by the engine directly or by the Python
projection. These tests run each case through `swe_native.resolve_evidence`
(the engine) and compare the result against what the adapter reports after
reading it back.

They are the regression against the failure mode the owner named: one need
becoming RESOLVED in Python and INSUFFICIENT_EVIDENCE in Rust.
"""

from __future__ import annotations

from typing import Any

import pytest

swe_native = pytest.importorskip("swe_native")

from app.swe.needs import (  # noqa: E402
    EvidenceJudgement,
    project_evidence_assessment,
    project_need,
    project_provenance,
    read_evidence,
    read_need_state,
)

NEED = {"fact": "fact_a", "subject": "subject_a"}
POLICY = {"uncertain_blocks_scope": True, "require_provenance": True}


def engine_resolve(
    assessments: list[dict[str, Any]], *, policy: dict[str, bool] = POLICY
) -> dict[str, Any]:
    """The normative path: whatever the engine says is the answer."""
    return swe_native.resolve_evidence(
        NEED,
        assessments,
        policy["uncertain_blocks_scope"],
        policy["require_provenance"],
    )


def adapter_view(result: dict[str, Any]) -> dict[str, Any]:
    """What the Python adapter reports after reading the engine's result."""
    state = read_need_state(result)
    evidence = [read_evidence(entry) for entry in result["evidence"]]
    return {"status": state["status"], "evidence": evidence}


def adjudicated(
    value: str,
    *,
    admissibility: str = "Admitted",
    key: str | None = None,
    scope: str = "scope_a",
    role: str | None = None,
    source: str | None = "source_a",
) -> dict[str, Any]:
    return project_evidence_assessment(
        EvidenceJudgement(
            fact=NEED["fact"],
            subject=NEED["subject"],
            admissibility=admissibility,
            value=value,
            equivalence_key=key if key is not None else value,
            conflict_scope=scope,
            operational_role=role,
            provenance=project_provenance(source_id=source) if source else None,
        )
    )


def assert_projection_matches_engine(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    """The core differential assertion."""
    engine = engine_resolve(assessments)
    projected = adapter_view(engine)
    # The adapter must report exactly what the engine decided.
    assert projected["status"] == engine["status"]
    assert projected["evidence"] == [
        {
            "fact": entry["fact"],
            "subject": entry["subject"],
            "value": entry["value"],
            "status": entry["status"],
            "source_id": entry["source_id"],
            "reason_code": entry["reason_code"],
        }
        for entry in engine["evidence"]
    ]
    # And the engine's verdict must be one the adapter knows how to report.
    assert projected["status"] in {"UNRESOLVED", "RESOLVED", "AMBIGUOUS"}
    return engine


CASES = {
    "single_verified": [adjudicated("value_a")],
    "rejected_plus_verified": [
        adjudicated("value_a"),
        adjudicated("", admissibility="NotAdmitted", key=None),
    ],
    "equivalent_values": [adjudicated("value_a"), adjudicated("value_a")],
    "normalised_equal_keys": [
        adjudicated("value_a", key="a"),
        adjudicated("value a", key="a"),
    ],
    "competing_values": [adjudicated("value_a"), adjudicated("value_b")],
    "different_roles": [
        adjudicated("value_a", role="role_a"),
        adjudicated("value_b", role="role_b"),
    ],
    "unknown_role_competes": [adjudicated("value_a"), adjudicated("value_b", role="role_b")],
    "uncertain_alone": [adjudicated("value_a", admissibility="Uncertain")],
    "no_provenance": [adjudicated("value_a", source=None)],
    "different_scopes": [
        adjudicated("value_a", scope="scope_a"),
        adjudicated("value_b", scope="scope_b"),
    ],
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_engine_and_projection_agree(case: str) -> None:
    assert_projection_matches_engine(CASES[case])


def test_competing_values_never_resolve_in_either_layer() -> None:
    """The exact failure mode the owner named."""
    engine = assert_projection_matches_engine(CASES["competing_values"])
    assert engine["status"] == "AMBIGUOUS"
    assert all(entry["status"] == "AMBIGUOUS" for entry in engine["evidence"])


def test_rejected_does_not_block_an_accepted_value() -> None:
    engine = assert_projection_matches_engine(CASES["rejected_plus_verified"])
    assert engine["status"] == "RESOLVED"
    statuses = sorted(entry["status"] for entry in engine["evidence"])
    assert statuses == ["REJECTED", "VERIFIED"]


def test_unknown_role_counts_as_competing_in_both_layers() -> None:
    engine = assert_projection_matches_engine(CASES["unknown_role_competes"])
    assert engine["status"] == "AMBIGUOUS"


def test_adapter_cannot_override_the_engine() -> None:
    """The adapter reads the engine; there is no path where it decides again."""
    engine = engine_resolve(CASES["competing_values"])
    assert engine["status"] == "AMBIGUOUS"
    reported = read_need_state({**engine, "status": "AMBIGUOUS"})
    assert reported["status"] == "AMBIGUOUS"
    # And an unknown status from the wire is refused rather than reinterpreted.
    with pytest.raises(Exception, match="unknown need status"):
        read_need_state({**engine, "status": "RESOLVED_MAYBE"})


def test_need_projection_round_trips_through_the_engine_shape() -> None:
    projected = project_need(fact="fact_a", subject="subject_a", priority="SUPPORTING")
    assert projected["priority"] == "SUPPORTING"
    assert projected["schema_version"] == 1
