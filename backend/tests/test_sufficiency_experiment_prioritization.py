"""B3 pair ordering: pure ranking, pluggable for a later SSR scorer."""

from __future__ import annotations

import pytest

from app.services.research.sufficiency_experiment.prioritization import (
    prioritize_pairs,
)
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    PairCandidate,
)


def _claim(claim_id, text, source_id="source-a"):
    return ClaimCandidate(
        claim_id=claim_id,
        evidence_id=claim_id.split(":")[0],
        source_id=source_id,
        passage_id="p0",
        start=0,
        end=len(text),
        text=text,
        normalized_text=text.lower(),
        canonical_key=claim_id,
        research_need_ids=("research_1",),
        extraction_method="sentence",
        extraction_status="extracted",
    )


def _pair(pair_id, left, right, features=()):
    return PairCandidate(
        pair_id=pair_id,
        need_id="research_1",
        left_claim_id=left,
        right_claim_id=right,
        score=0.0,
        sources=("deterministic",),
        features=features,
    )


class FakeEmbedding:
    provider_id = "fake"
    model = "fake-embedding"
    dimension = 2

    async def embed(self, texts):
        vectors = {
            "Hundar får vistas i parken.": [1.0, 0.0],
            "Hundar tillåts i parken.": [0.9, 0.1],
            "Katter äter fisk.": [-1.0, 0.0],
        }
        return [vectors[text] for text in texts]


async def test_current_order_is_preserved() -> None:
    claims = {
        "c1": _claim("c1", "Hundar får vistas i parken."),
        "c2": _claim("c2", "Katter äter fisk."),
    }
    pairs = (_pair("p1", "c1", "c2"),)
    assert await prioritize_pairs(pairs, claims, ordering="current") == pairs


async def test_metadata_lifts_opposite_polarity_pair() -> None:
    claims = {
        "c1": _claim("c1", "Hundar får vistas i parken."),
        "c2": _claim("c2", "Hundar förbjuds i parken."),
        "c3": _claim("c3", "Hundar vistas i parken."),
    }
    polarity = _pair(
        "polarity", "c1", "c2", features=(("rarity", 1.0), ("canonical_downweight", 1.0))
    )
    neutral = _pair(
        "neutral", "c1", "c3", features=(("rarity", 1.0), ("canonical_downweight", 1.0))
    )
    ranked = await prioritize_pairs(
        (neutral, polarity), claims, ordering="metadata"
    )
    assert ranked[0].pair_id == "polarity"


async def test_embedding_orders_similar_claims_first() -> None:
    claims = {
        "c1": _claim("c1", "Hundar får vistas i parken."),
        "c2": _claim("c2", "Hundar tillåts i parken."),
        "c3": _claim("c3", "Katter äter fisk."),
    }
    similar = _pair("similar", "c1", "c2")
    far = _pair("far", "c1", "c3")
    ranked = await prioritize_pairs(
        (far, similar), claims, ordering="embedding", embedding_provider=FakeEmbedding()
    )
    assert ranked[0].pair_id == "similar"


async def test_unknown_ordering_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unknown pair ordering"):
        await prioritize_pairs((), {}, ordering="ssr")
