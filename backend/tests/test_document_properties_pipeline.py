"""Pipeline: discovery -> Jev -> persistence over the OverGraph knowledge graph."""

from __future__ import annotations

from app.jev.system import JevSystemOneResult, JevUsage
from app.services.document_properties.pipeline import (
    LocalDenseConfig,
    discover_and_verify,
)
from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.claims import find_claims_by_class
from app.services.overgraph.text_units import upsert_text_units


def _seed_unit(catalog, *, unit_id, document_version_id, document_id, ordinal, text):
    upsert_text_units(
        catalog,
        [
            TextUnit(
                id=unit_id,
                document_version_id=document_version_id,
                document_id=document_id,
                section_id="sec-1",
                ordinal=ordinal,
                text=text,
                content_hash=hash_text(text),
            )
        ],
        scope=customer_scope(1),
        section_titles={"sec-1": "Sekretess"},
    )


class SupportedJev:
    def __init__(self):
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        return JevSystemOneResult(
            answers={"verdict": {"choice": "SUPPORTED"}, "source": {"choice": "tu-a:0"}},
            model=model, latency_ms=1.0, input_chars=0, usage=JevUsage(), raw={},
        )


async def test_pipeline_persists_supported_claim(research_overgraph):
    catalog = research_overgraph
    _seed_unit(
        catalog, unit_id="tu-a", document_version_id="ver-a", document_id="doc-a",
        ordinal=0, text="Arbetstagaren har tystnadsplikt om företagshemligheter.",
    )

    result = await discover_and_verify(
        catalog,
        customer_id=1,
        document_version_id="ver-a",
        jev=SupportedJev(),
        model="test",
        timeout_seconds=1.0,
    )
    assert result.supported == 1
    claims, _ = find_claims_by_class(
        catalog, scope=customer_scope(1), class_id="confidentiality_obligation"
    )
    assert len(claims) == 1
    assert claims[0].props["document_id"] == "doc-a"


class FakeEmbeddings:
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class FakeStored:
    async def get_text_unit_embeddings(self, *, document_id, document_version_id, text_unit_ids):
        return {unit_id: [1.0, 0.0] for unit_id in text_unit_ids}


class RecoveryJev:
    def __init__(self):
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        if self.calls == 1:
            return JevSystemOneResult(
                answers={"verdict": {"choice": "UNSUPPORTED"}, "source": {"choice": "none"}},
                model=model, latency_ms=1.0, input_chars=0, usage=JevUsage(), raw={},
            )
        source = next((key for key in questions["source"]["criteria"] if key != "none"), "none")
        return JevSystemOneResult(
            answers={"verdict": {"choice": "SUPPORTED"}, "source": {"choice": source}},
            model=model, latency_ms=1.0, input_chars=0, usage=JevUsage(), raw={},
        )


async def test_local_dense_recovers_unsupported_candidate(research_overgraph):
    catalog = research_overgraph
    _seed_unit(
        catalog, unit_id="tu-a", document_version_id="ver-a", document_id="doc-a",
        ordinal=0, text="Arbetstagaren har tystnadsplikt om företagshemligheter.",
    )
    _seed_unit(
        catalog, unit_id="tu-b", document_version_id="ver-a", document_id="doc-a",
        ordinal=1, text="Parterna ska samarbeta.",
    )

    result = await discover_and_verify(
        catalog,
        customer_id=1,
        document_version_id="ver-a",
        jev=RecoveryJev(),
        model="test",
        timeout_seconds=1.0,
        local_dense=LocalDenseConfig(
            question="Vilka avtal innehåller en sekretessplikt?",
            embeddings=FakeEmbeddings(),
            stored=FakeStored(),
            k=5,
        ),
    )
    assert result.supported == 1
    assert result.recovered == 1
