"""Evidence-anchored document properties (deterministic discovery + Jev verification).

A document property is a typed assertion about a document (e.g. "this contract
imposes a confidentiality obligation"), grounded in TextUnits and persisted as
a typed knowledge claim when Jev supports it, or as a verification observation
when it is unsupported or undecided.
"""

from app.services.document_properties.model import (
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    DocumentProperty,
    PropertyVerification,
)

__all__ = [
    "SUPPORTED",
    "UNDECIDED",
    "UNSUPPORTED",
    "DocumentProperty",
    "PropertyVerification",
]
