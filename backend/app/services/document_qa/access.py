"""Workspace and document permission checked before any tenant graph access."""

from __future__ import annotations

from dataclasses import dataclass


class QaPermissionError(PermissionError):
    """Caller lacks workspace or document access inside the tenant database."""


class QaStoreError(RuntimeError):
    """Tenant graph write failed. The user answer must still be returned."""


STORE_FAILURES = (
    QaStoreError,
    QaPermissionError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
)


def require_customer_id(value: object) -> int:
    if type(value) is not int:
        raise ValueError("tenant catalog requires a verified integer customer_id")
    if value < 1:
        raise ValueError("customer_id must be a verified positive integer")
    return value


@dataclass(frozen=True)
class Viewer:
    customer_id: int
    workspace_id: str
    readable_document_ids: frozenset[str]
    readable_version_ids: frozenset[str]

    def __post_init__(self) -> None:
        require_customer_id(self.customer_id)
        if not self.workspace_id.strip():
            raise ValueError("viewer is missing workspace context")

    def can_read(self, document_id: str, version_id: str) -> bool:
        return (
            document_id in self.readable_document_ids
            and version_id in self.readable_version_ids
        )

    def require(self, document_id: str, version_id: str) -> None:
        if not self.can_read(document_id, version_id):
            raise QaPermissionError("workspace or document is not readable")
