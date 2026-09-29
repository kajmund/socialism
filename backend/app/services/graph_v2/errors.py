"""Errors used to distinguish invalid graph state from retryable dependencies."""


class PermanentGraphError(ValueError):
    """A persisted payload or graph invariant cannot be repaired by retrying."""


class JevMalformedResponseError(RuntimeError):
    """Jev returned a response that cannot be interpreted; retry the projection."""
