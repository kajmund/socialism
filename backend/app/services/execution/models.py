"""Status vocabularies for the generic execution domain.

Product names are Run → Attempt → EvidenceSet. Persistence uses
``execution_runs`` / ``execution_attempts`` because simulation already owns
``runs``.
"""

from __future__ import annotations

from typing import Literal

AttemptStatus = Literal[
    "created",
    "researching",
    "ready",
    "running",
    "completed",
    "failed",
]

ATTEMPT_STATUSES: tuple[AttemptStatus, ...] = (
    "created",
    "researching",
    "ready",
    "running",
    "completed",
    "failed",
)

# ResearchPlan can move created → researching without locking snapshots.
PREPARATION_STATUSES: frozenset[AttemptStatus] = frozenset({"created", "researching"})
SNAPSHOT_LOCKED_STATUSES: frozenset[AttemptStatus] = frozenset(
    {"ready", "running", "completed", "failed"}
)
# Failed research may leave EvidenceSet building; only execution-ready
# statuses require a frozen set.
EVIDENCE_REQUIRED_FROZEN_STATUSES: frozenset[AttemptStatus] = frozenset(
    {"ready", "running", "completed"}
)
TERMINAL_STATUSES: frozenset[AttemptStatus] = frozenset({"completed", "failed"})
# Clone reuses a frozen EvidenceSet; source must already be executable or
# finished. created/researching/running are not cloneable.
CLONEABLE_ATTEMPT_STATUSES: frozenset[AttemptStatus] = frozenset(
    {"ready", "completed", "failed"}
)

# researching is the in-flight ResearchPlan → ResearchRouter claim.
ALLOWED_ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    "created": frozenset({"researching", "ready", "running", "failed"}),
    "researching": frozenset({"ready", "running", "failed"}),
    "ready": frozenset({"running", "failed"}),
    "running": frozenset({"completed", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
}

EvidenceSetStatus = Literal["building", "frozen", "failed"]

EVIDENCE_SET_STATUSES: tuple[EvidenceSetStatus, ...] = ("building", "frozen", "failed")

# Documented examples only — attempt_type is an extensible string, not a DB enum.
KNOWN_ATTEMPT_TYPES: tuple[str, ...] = (
    "generic_panel",
    "structured_scoring",
    "word_review",
)
