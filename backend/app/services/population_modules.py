"""Module tags stored on expert-panel recipes (recipe.modules)."""

from __future__ import annotations


def panel_engine_module_ids() -> frozenset[str]:
    from app.modules.registry import MODULE_REGISTRY

    return frozenset(
        mid
        for mid, manifest in MODULE_REGISTRY.items()
        if "panel_engine" in manifest.components
    )


def modules_from_recipe(recipe: dict | None) -> list[str]:
    raw = (recipe or {}).get("modules")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def normalize_panel_modules(modules: list[str]) -> list[str]:
    allowed = panel_engine_module_ids()
    out: list[str] = []
    seen: set[str] = set()
    for item in modules:
        value = item.strip()
        if not value:
            continue
        if value not in allowed:
            raise ValueError(f"unknown panel module: {value}")
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def recipe_with_normalized_modules(recipe: dict | None) -> dict:
    stored = dict(recipe or {})
    if "modules" not in stored:
        return stored
    raw = stored["modules"]
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("recipe.modules must be a list of module ids")
    stored["modules"] = normalize_panel_modules(raw)
    return stored
