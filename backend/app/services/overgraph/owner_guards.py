"""Process-local guards for owner mode."""

from __future__ import annotations


class DirectWriteForbidden(RuntimeError):
    """A backend in owner mode attempted a direct knowledge-catalog write."""


_direct_writes_forbidden = False


def set_direct_writes_forbidden(enabled: bool) -> None:
    """Runtime guard: only the owner process may write a knowledge catalog."""
    global _direct_writes_forbidden
    _direct_writes_forbidden = enabled


def assert_direct_write_allowed(kind: str) -> None:
    if _direct_writes_forbidden and kind == "knowledge":
        raise DirectWriteForbidden(
            "direct knowledge-catalog writes are forbidden in owner mode; "
            "route the mutation through the Owner"
        )
