"""Fail-closed errors for the generic execution domain."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base error for Run → Attempt → EvidenceSet operations."""


class ExecutionNotFoundError(ExecutionError):
    def __init__(self, kind: str, identifier: str) -> None:
        super().__init__(f"{kind} not found: {identifier}")
        self.kind = kind
        self.identifier = identifier


class ExecutionScopeError(ExecutionError):
    """Cross-customer or cross-run attachment / ownership violation."""


class ExecutionFrozenError(ExecutionError):
    """A frozen EvidenceSet cannot be mutated."""


class ExecutionImmutableError(ExecutionError):
    """Execution-defining snapshots cannot change after an Attempt has started."""


class ExecutionStatusError(ExecutionError):
    """Illegal Attempt or EvidenceSet status transition."""
