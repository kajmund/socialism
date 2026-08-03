"""Apply @@SLOT_name@@ replacements on report HTML templates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SLOT_RE = re.compile(r"@@SLOT_([a-z0-9_]+)@@")

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def list_slots_in_template(html: str) -> list[str]:
    return sorted(set(_SLOT_RE.findall(html)))


def apply_slots(html: str, slots: dict[str, Any], *, strict: bool = False) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in slots:
            if strict:
                raise KeyError(f"Saknar slot: {key}")
            return ""
        val = slots[key]
        return "" if val is None else str(val)

    return _SLOT_RE.sub(repl, html)


def load_template(path: Path | None = None) -> str:
    p = path or (ASSETS_DIR / "report_template.html")
    return p.read_text(encoding="utf-8")


def dry_run_defaults(slots: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in slots:
        if s.endswith("_html"):
            out[s] = f'<p class="sec-intro"><em>Platshållare ({s}).</em></p>'
        else:
            out[s] = f"… ({s})"
    return out
