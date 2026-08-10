"""Map SCB population tables to Opinionssimulator recipe weights."""

from __future__ import annotations

from typing import Any

from integrations.scb.client import ScbClient, VariableSelection

POPULATION_TABLE_ID = "TAB638"
_ADULT_AGE_CODES = [str(age) for age in range(18, 100)] + ["100+"]
_CIVILSTAND_CODES = ["OG", "G", "SK", "ÄNKL"]
_KON_CODES = ["1", "2"]


def _percent_weights(counts: dict[str, float]) -> list[dict[str, str | int]]:
    total = sum(counts.values())
    if total <= 0:
        equal = max(1, len(counts))
        share = 100 // equal
        rows = [{"k": key, "l": key, "v": share} for key in counts]
        rows[0]["v"] = int(rows[0]["v"]) + (100 - share * equal)  # type: ignore[arg-type]
        return rows
    rows: list[dict[str, str | int]] = []
    running = 0
    keys = list(counts.keys())
    for index, key in enumerate(keys):
        if index == len(keys) - 1:
            value = 100 - running
        else:
            value = round(counts[key] * 100 / total)
            running += value
        rows.append({"k": key, "l": key, "v": max(0, value)})
    return rows


def _parse_jsonstat_values(payload: dict[str, Any]) -> list[float | None]:
    raw = payload.get("value")
    if not isinstance(raw, list):
        return []
    out: list[float | None] = []
    for item in raw:
        if item is None:
            out.append(None)
        else:
            out.append(float(item))
    return out


def _age_bucket(age_code: str) -> str:
    if age_code == "100+":
        return "aldre"
    age = int(age_code)
    if age <= 34:
        return "ung"
    if age <= 59:
        return "medel"
    return "aldre"


async def fetch_population_distribution(
    region_code: str,
    *,
    year: str = "2024",
    client: ScbClient | None = None,
) -> dict[str, Any]:
    """Fetch age/kön/civilstånd weights for one municipality (kommunkod)."""
    scb = client or ScbClient()
    meta = await scb.get_table_meta(POPULATION_TABLE_ID)
    region_labels = (
        meta.get("dimension", {}).get("Region", {}).get("category", {}).get("label", {})
    )
    region_label = region_labels.get(region_code, region_code)

    filters: list[VariableSelection] = [
        {"variableCode": "Region", "valueCodes": [region_code]},
        {"variableCode": "Civilstand", "valueCodes": _CIVILSTAND_CODES},
        {"variableCode": "Alder", "valueCodes": _ADULT_AGE_CODES},
        {"variableCode": "Kon", "valueCodes": _KON_CODES},
        {"variableCode": "ContentsCode", "valueCodes": ["BE0101N1"]},
        {"variableCode": "Tid", "valueCodes": [year]},
    ]
    payload = await scb.query(POPULATION_TABLE_ID, filters)
    values = _parse_jsonstat_values(payload)
    size = payload.get("size") or []
    if len(size) < 4 or not values:
        raise ValueError(f"No population data for region {region_code} ({year})")

    civil_codes = list(
        payload["dimension"]["Civilstand"]["category"]["index"].keys()
    )
    age_codes = list(payload["dimension"]["Alder"]["category"]["index"].keys())
    kon_codes = list(payload["dimension"]["Kon"]["category"]["index"].keys())

    age_counts = {"ung": 0.0, "medel": 0.0, "aldre": 0.0}
    kon_counts = {"kvinna": 0.0, "man": 0.0}
    civil_counts = {code: 0.0 for code in civil_codes}

    idx = 0
    for _region in range(size[0]):
        for civil_code in civil_codes:
            for age_code in age_codes:
                for kon_code in kon_codes:
                    if idx >= len(values):
                        break
                    value = values[idx]
                    idx += 1
                    if value is None:
                        continue
                    age_counts[_age_bucket(age_code)] += value
                    if kon_code == "1":
                        kon_counts["man"] += value
                    else:
                        kon_counts["kvinna"] += value
                    civil_counts[civil_code] += value

    civil_labels = payload["dimension"]["Civilstand"]["category"]["label"]
    age_rows = _percent_weights(age_counts)
    age_rows = [
        {
            "k": row["k"],
            "l": {"ung": "Ung (20–34)", "medel": "Medel (35–59)", "aldre": "Äldre (60+)"}[
                str(row["k"])
            ],
            "v": row["v"],
        }
        for row in age_rows
    ]
    kon_rows = _percent_weights(kon_counts)
    kon_rows = [
        {
            "k": row["k"],
            "l": "Kvinna" if row["k"] == "kvinna" else "Man",
            "v": row["v"],
        }
        for row in kon_rows
    ]

    return {
        "region_code": region_code,
        "region_label": region_label,
        "year": year,
        "source_table": POPULATION_TABLE_ID,
        "dist": {
            "age": {"label": "Ålder", "rows": age_rows},
            "kön": {"label": "Kön", "rows": kon_rows},
        },
        "civilstand": {
            civil_labels.get(code, code): int(count)
            for code, count in civil_counts.items()
        },
        "notes": [
            "Åldersgrupperna motsvarar Opinionssimulator: ung 20–34, medel 35–59, äldre 60+.",
            "Kön från SCB (män/kvinnor) mappas till Man/Kvinna i population builder.",
            "Civilstånd redovisas som rådata — mappa manuellt till livssituation vid behov.",
        ],
    }


async def find_region_code(query: str, *, client: ScbClient | None = None) -> str | None:
    """Resolve a municipality name to kommunkod using TAB638 metadata."""
    needle = query.strip().casefold()
    if not needle:
        return None
    scb = client or ScbClient()
    meta = await scb.get_table_meta(POPULATION_TABLE_ID)
    labels = meta.get("dimension", {}).get("Region", {}).get("category", {}).get("label", {})
    if needle.isdigit() and needle in labels:
        return needle
    for code, label in labels.items():
        if code == "00":
            continue
        if needle in label.casefold():
            return code
    return None
