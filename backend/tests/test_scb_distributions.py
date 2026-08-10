"""Tests for SCB → population distribution mapping."""

from __future__ import annotations

import pytest

from integrations.scb.distributions import fetch_population_distribution, find_region_code


class FakeScbClient:
    async def get_table_meta(self, _table_id: str, *, lang: str = "sv"):
        return {
            "dimension": {
                "Region": {
                    "category": {
                        "label": {"0380": "Uppsala", "00": "Riket"},
                    }
                }
            }
        }

    async def query(self, _table_id: str, _filters, *, lang: str = "sv", output_format: str = "json-stat2"):
        return {
            "size": [1, 2, 2, 2, 1, 1],
            "dimension": {
                "Civilstand": {
                    "category": {
                        "index": {"OG": 0, "G": 1},
                        "label": {"OG": "ogifta", "G": "gifta"},
                    }
                },
                "Alder": {"category": {"index": {"20": 0, "40": 1}}},
                "Kon": {"category": {"index": {"1": 0, "2": 1}, "label": {"1": "män", "2": "kvinnor"}}},
            },
            "value": [100, 200, 150, 250, 50, 50, 75, 125],
        }


@pytest.mark.asyncio
async def test_find_region_code_by_name():
    client = FakeScbClient()
    assert await find_region_code("uppsala", client=client) == "0380"


@pytest.mark.asyncio
async def test_fetch_population_distribution_builds_percentages():
    payload = await fetch_population_distribution("0380", client=FakeScbClient())
    assert payload["region_label"] == "Uppsala"
    age_rows = payload["dist"]["age"]["rows"]
    assert sum(row["v"] for row in age_rows) == 100
    kon_rows = payload["dist"]["kön"]["rows"]
    assert sum(row["v"] for row in kon_rows) == 100
    assert {row["l"] for row in kon_rows} == {"Man", "Kvinna"}
