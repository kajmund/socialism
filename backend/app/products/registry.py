"""Customer-level products that replace the standard application shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductManifest:
    id: str
    name: str


PRODUCT_REGISTRY: dict[str, ProductManifest] = {
    "sme": ProductManifest(id="sme", name="SME"),
}
