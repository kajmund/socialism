"""One-off import of SCB name statistics into static persona catalog data.

Run from repo root (requires network access to statistikdatabasen.scb.se):

    PYTHONPATH=backend:. python backend/scripts/import_scb_names.py

Re-run manually when SCB tables change; output is checked in as
``app/services/persona_catalog_scb_names.py``. Persona generation reads only
that static module — no runtime SCB calls.

PxWebApi v2 tables (spec BE0001* ids 404 on v2):
  TAB615 — top-100 first names by birth year (1922–2021), gender in code prefix
  TAB616 — top-100 surnames by registration year (1980–2021)
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "backend"))

from integrations.scb.client import ScbClient, VariableSelection

FIRST_NAMES_TABLE = "TAB615"
SURNAMES_TABLE = "TAB616"
FIRST_NAMES_CONTENT = "BE0001AM"
SURNAMES_CONTENT = "BE0001AD"
SAMPLE_YEARS = list(range(1925, 2021, 5))
SURNAMES_YEAR = "2020"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "app/services/persona_catalog_scb_names.py"


def _category_codes(payload: dict[str, Any], dim: str) -> list[str]:
    cat = payload["dimension"][dim]["category"]
    idx = cat["index"]
    if isinstance(idx, dict):
        return list(idx.keys())
    return list(idx)


def _category_labels(payload: dict[str, Any], dim: str) -> dict[str, str]:
    return payload["dimension"][dim]["category"]["label"]


def _decade_for_birth_year(year: int) -> str:
    return str(round(year / 10) * 10)


def _parse_name_counts(payload: dict[str, Any]) -> dict[str, dict[int, float]]:
    """Return {fornamn_code: {birth_year: count}}."""
    name_codes = _category_codes(payload, "Fornamn")
    year_codes = _category_codes(payload, "Tid")
    size = payload["size"]
    values = payload.get("value") or []
    n_content = size[1]
    n_year = size[2]
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for i_name, name_code in enumerate(name_codes):
        base = i_name * n_content * n_year
        for i_year, year_code in enumerate(year_codes):
            idx = base + i_year
            raw = values[idx] if idx < len(values) else None
            if raw is None:
                continue
            count = float(raw)
            if count <= 0:
                continue
            out[name_code][int(year_code)] = count
    return out


def _gender_from_fornamn_code(code: str) -> str | None:
    if code.startswith("1"):
        return "M"
    if code.startswith("2"):
        return "F"
    return None


def _display_name(code: str, labels: dict[str, str]) -> str:
    return labels.get(code, code).strip()


async def fetch_first_names_by_decade(client: ScbClient) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    meta = await client.get_table_meta(FIRST_NAMES_TABLE)
    name_codes = _category_codes(meta, "Fornamn")
    name_labels = meta["dimension"]["Fornamn"]["category"]["label"]
    year_codes = [str(y) for y in SAMPLE_YEARS]

    payload = await client.query(
        FIRST_NAMES_TABLE,
        [
            {"variableCode": "Fornamn", "valueCodes": name_codes},
            {"variableCode": "ContentsCode", "valueCodes": [FIRST_NAMES_CONTENT]},
            {"variableCode": "Tid", "valueCodes": year_codes},
        ],
    )
    counts = _parse_name_counts(payload)

    by_decade_f: dict[str, set[str]] = defaultdict(set)
    by_decade_m: dict[str, set[str]] = defaultdict(set)
    for code, year_counts in counts.items():
        gender = _gender_from_fornamn_code(code)
        if gender is None:
            continue
        label = _display_name(code, name_labels)
        if not label:
            continue
        for year in year_counts:
            decade = _decade_for_birth_year(year)
            if gender == "F":
                by_decade_f[decade].add(label)
            else:
                by_decade_m[decade].add(label)

    decades = sorted(set(by_decade_f) | set(by_decade_m), key=int)
    first_f = {d: sorted(by_decade_f[d]) for d in decades if by_decade_f[d]}
    first_m = {d: sorted(by_decade_m[d]) for d in decades if by_decade_m[d]}
    return first_f, first_m


async def fetch_surnames(client: ScbClient) -> list[str]:
    meta = await client.get_table_meta(SURNAMES_TABLE)
    surname_codes = _category_codes(meta, "Efternamn")
    labels = meta["dimension"]["Efternamn"]["category"]["label"]

    payload = await client.query(
        SURNAMES_TABLE,
        [
            {"variableCode": "Efternamn", "valueCodes": surname_codes},
            {"variableCode": "ContentsCode", "valueCodes": [SURNAMES_CONTENT]},
            {"variableCode": "Tid", "valueCodes": [SURNAMES_YEAR]},
        ],
    )
    out: set[str] = set()
    values = payload.get("value") or []
    for i, code in enumerate(surname_codes):
        raw = values[i] if i < len(values) else None
        if raw is None or float(raw) <= 0:
            continue
        name = _display_name(code, labels)
        if name:
            out.add(name)
    return sorted(out)


def _format_dict(name: str, data: dict[str, list[str]]) -> str:
    lines = [f"{name}: dict[str, list[str]] = {{"]
    for key in sorted(data, key=int):
        names = data[key]
        inner = ", ".join(repr(n) for n in names)
        lines.append(f'    "{key}": [{inner}],')
    lines.append("}")
    return "\n".join(lines)


def _format_list(name: str, items: list[str]) -> str:
    inner = ",\n    ".join(repr(i) for i in items)
    return f"{name}: list[str] = [\n    {inner},\n]"


def write_output(
    *,
    first_f: dict[str, list[str]],
    first_m: dict[str, list[str]],
    surnames: list[str],
) -> None:
    decades = sorted(set(first_f) | set(first_m), key=int)
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    body = f'''"""Static SCB name data for age-weighted persona sampling.

Generated by ``backend/scripts/import_scb_names.py`` on {generated}.
Do not edit by hand — re-run the import script if SCB tables are updated.

Sources (PxWebApi v2):
  {FIRST_NAMES_TABLE} — top-100 first names by birth year, sampled every 5 years
  {SURNAMES_TABLE} — top-100 surnames ({SURNAMES_YEAR})
"""

from __future__ import annotations

DECADES: tuple[str, ...] = {tuple(decades)!r}

{_format_dict("FIRST_NAMES_BY_DECADE_F", first_f)}

{_format_dict("FIRST_NAMES_BY_DECADE_M", first_m)}

{_format_list("SCB_LASTN", surnames)}
'''
    OUTPUT_PATH.write_text(body, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(decades)} decades, {len(surnames)} surnames)")


async def main() -> None:
    client = ScbClient()
    first_f, first_m = await fetch_first_names_by_decade(client)
    surnames = await fetch_surnames(client)
    if not first_f or not first_m:
        raise SystemExit("No first-name decades imported from SCB")
    if not surnames:
        raise SystemExit("No surnames imported from SCB")
    write_output(first_f=first_f, first_m=first_m, surnames=surnames)


if __name__ == "__main__":
    asyncio.run(main())
