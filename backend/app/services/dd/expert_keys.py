"""Shared slug helpers for DD expert role / persona keys."""

from __future__ import annotations

import re

_EXPERT_KEY_RE = re.compile(r"[^a-z0-9]+")


def expert_role_key(label: str) -> str:
    slug = _EXPERT_KEY_RE.sub("_", label.strip().casefold()).strip("_")
    return slug or "expert"


def expert_persona_id(customer_id: int, catalog_key: str) -> str:
    """Stable Persona.id for a catalog expert, unique per customer × key."""
    key = catalog_key.strip()
    if not key:
        raise ValueError("catalog_key is required")
    return f"exp_{customer_id}_{key}"


def persona_catalog_key(persona) -> str:
    """Catalog role key encoded in a seeded expert Persona.id."""
    prefix = f"exp_{persona.customer_id}_"
    if persona.id.startswith(prefix):
        return persona.id[len(prefix) :]
    if persona.id.startswith("exp_"):
        return persona.id[4:]
    return expert_role_key(persona.name)
