"""Build variant tick plans from a Run row (no OASIS runtime imports)."""

from __future__ import annotations

from app.database.models import Run
from app.schemas.domain import Tick


def parse_ticks(raw: list | None) -> list[Tick]:
    return [Tick.model_validate(t) for t in (raw or [])]


def variant_plans(run: Run) -> list[tuple[str, str, list[Tick]]]:
    """Return (variant_id, label, ticks) for each simulation to run.

    Without a branch: one plan over main_ticks.
    With a branch: Version A and B, each = stem (through afterIndex) + branch ticks.
    """
    main = parse_ticks(run.main_ticks)
    branch = run.branch
    if not branch:
        return [("main", "Huvudtidslinje", main)]

    if isinstance(branch, dict):
        raw_after = branch.get("afterIndex", 0)
        after = int(raw_after) if raw_after is not None else 0
        a_raw = branch.get("a") or []
        b_raw = branch.get("b") or []
    else:
        after = branch.afterIndex
        a_raw = branch.a
        b_raw = branch.b

    mode = branch.get("mode", "ab") if isinstance(branch, dict) else getattr(branch, "mode", "ab")
    if mode == "stimulus_control":
        label_a, label_b = "Med stimulus", "Kontroll (ingen injektion)"
    else:
        label_a, label_b = "Version A", "Version B"

    stem = main[: max(0, after + 1)]
    return [
        ("a", label_a, stem + parse_ticks(a_raw)),
        ("b", label_b, stem + parse_ticks(b_raw)),
    ]
