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
from itertools import product
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "backend"))

from integrations.scb.client import ScbClient

FIRST_NAMES_TABLE = "TAB615"
SURNAMES_TABLE = "TAB616"
FIRST_NAMES_CONTENT = "BE0001AM"
SURNAMES_CONTENT = "BE0001AD"
SAMPLE_YEARS = list(range(1925, 2021, 5))
SURNAMES_YEAR = "2020"
TOP_NAMES_PER_YEAR = 50
MIN_UNIQUE_DECADE_RATIO = 0.5
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "app/services/persona_catalog_scb_names.py"


def _category_codes(payload: dict[str, Any], dim: str) -> list[str]:
    cat = payload["dimension"][dim]["category"]
    idx = cat["index"]
    if isinstance(idx, dict):
        return list(idx.keys())
    return list(idx)


def _dimension_codes(payload: dict[str, Any]) -> list[list[str]]:
    return [_category_codes(payload, dim) for dim in payload["id"]]


def _flat_index(sizes: list[int], indices: tuple[int, ...]) -> int:
    """JSON-stat2: last dimension in ``id`` varies fastest."""
    stride = 1
    flat = 0
    for i in range(len(sizes) - 1, -1, -1):
        flat += indices[i] * stride
        stride *= sizes[i]
    return flat


def _iter_jsonstat_cells(payload: dict[str, Any]):
    dims = payload["id"]
    sizes = payload["size"]
    values = payload.get("value") or []
    dim_codes = _dimension_codes(payload)
    for indices in product(*(range(size) for size in sizes)):
        idx = _flat_index(sizes, indices)
        raw = values[idx] if idx < len(values) else None
        coords = {dims[i]: dim_codes[i][indices[i]] for i in range(len(dims))}
        yield coords, raw


def _decade_for_birth_year(year: int) -> str:
    return str(round(year / 10) * 10)


def _gender_from_fornamn_code(code: str) -> str | None:
    if code.startswith("1"):
        return "M"
    if code.startswith("2"):
        return "F"
    return None


def _display_name(code: str, labels: dict[str, str]) -> str:
    return labels.get(code, code).strip()


def _top_names_by_birth_year(
    payload: dict[str, Any],
    name_labels: dict[str, str],
    *,
    top_n: int,
) -> dict[int, dict[str, list[str]]]:
    """Return {birth_year: {gender: [names ranked by count]}}."""
    ranked: dict[int, dict[str, list[tuple[float, str]]]] = defaultdict(
        lambda: {"F": [], "M": []}
    )
    for coords, raw in _iter_jsonstat_cells(payload):
        if coords.get("ContentsCode") != FIRST_NAMES_CONTENT:
            continue
        if raw is None:
            continue
        count = float(raw)
        if count <= 0:
            continue
        code = coords["Fornamn"]
        gender = _gender_from_fornamn_code(code)
        if gender is None:
            continue
        label = _display_name(code, name_labels)
        if not label:
            continue
        year = int(coords["Tid"])
        ranked[year][gender].append((count, label))

    out: dict[int, dict[str, list[str]]] = {}
    for year, by_gender in ranked.items():
        out[year] = {}
        for gender, pairs in by_gender.items():
            pairs.sort(key=lambda item: (-item[0], item[1]))
            seen: set[str] = set()
            names: list[str] = []
            for _, label in pairs:
                if label in seen:
                    continue
                seen.add(label)
                names.append(label)
                if len(names) >= top_n:
                    break
            out[year][gender] = names
    return out


def _bucket_first_names_by_decade(
    by_year: dict[int, dict[str, list[str]]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    by_decade_f: dict[str, set[str]] = defaultdict(set)
    by_decade_m: dict[str, set[str]] = defaultdict(set)
    for year, genders in by_year.items():
        decade = _decade_for_birth_year(year)
        for name in genders.get("F", []):
            by_decade_f[decade].add(name)
        for name in genders.get("M", []):
            by_decade_m[decade].add(name)

    decades = sorted(set(by_decade_f) | set(by_decade_m), key=int)
    first_f = {d: sorted(by_decade_f[d]) for d in decades if by_decade_f[d]}
    first_m = {d: sorted(by_decade_m[d]) for d in decades if by_decade_m[d]}
    return first_f, first_m


def _assert_decade_variation(
    first_f: dict[str, list[str]],
    first_m: dict[str, list[str]],
) -> None:
    for label, data in ("female", first_f), ("male", first_m):
        if len(data) < 4:
            raise SystemExit(f"SCB import sanity check failed: too few {label} decades")
        unique_lists = len({tuple(names) for names in data.values()})
        min_unique = max(2, int(len(data) * MIN_UNIQUE_DECADE_RATIO))
        if unique_lists < min_unique:
            raise SystemExit(
                "SCB import sanity check failed: "
                f"{label} decades too similar ({unique_lists}/{len(data)} unique lists, "
                f"need at least {min_unique})"
            )

    if set(first_f.get("1980", [])) == set(first_f.get("2010", [])):
        raise SystemExit(
            "SCB import sanity check failed: female 1980 and 2010 buckets are identical"
        )
    modern = set(first_f.get("2010", [])) | set(first_f.get("2000", []))
    if not {"Alice", "Elsa"} & modern:
        raise SystemExit(
            "SCB import sanity check failed: expected modern female names (Alice/Elsa) "
            "in 2000/2010 buckets"
        )


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
    by_year = _top_names_by_birth_year(payload, name_labels, top_n=TOP_NAMES_PER_YEAR)
    first_f, first_m = _bucket_first_names_by_decade(by_year)
    _assert_decade_variation(first_f, first_m)
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
    ranked: list[tuple[float, str]] = []
    for coords, raw in _iter_jsonstat_cells(payload):
        if coords.get("ContentsCode") != SURNAMES_CONTENT:
            continue
        if raw is None or float(raw) <= 0:
            continue
        code = coords["Efternamn"]
        name = _display_name(code, labels)
        if name:
            ranked.append((float(raw), name))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    seen: set[str] = set()
    out: list[str] = []
    for _, name in ranked:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


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
  TAB615 — top-{TOP_NAMES_PER_YEAR} first names per birth year (ranked by count;
    TAB615 rows are a fixed pool, so ranking — not mere count>0 — yields cohort-specific lists),
  {SURNAMES_TABLE} — top surnames ({SURNAMES_YEAR})
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
