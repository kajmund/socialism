"""One production registration for the official lagen.nu KnowledgeProvider."""

from __future__ import annotations

from app.services.research.provider import KnowledgeProviderDescriptor, ProviderAccess

LAGEN_NU_PROVIDER_ID = "lagen_nu"
LAGEN_NU_ADAPTER = "lagen_nu_research_source"
LAGEN_NU_DOMAIN = "law"
LAGEN_NU_JURISDICTION = "SE"
LAGEN_NU_PUBLICATION_NOTE = (
    "lagen.nu republishes material from official sources; use the publisher source URL "
    "for verification when available"
)
LAGEN_NU_EVIDENCE_NATURES: tuple[str, ...] = (
    "swedish_law",
    "swedish_case_law",
    "swedish_preparatory_works",
)
_MCP_SOURCE_BY_NATURE: dict[str, str] = {
    "swedish_law": "sfs",
    "swedish_case_law": "dv",
    "swedish_preparatory_works": "forarbete",
}


def mcp_source_for_nature(nature: str) -> str:
    try:
        return _MCP_SOURCE_BY_NATURE[nature]
    except KeyError as exc:
        raise ValueError(f"lagen.nu adapter does not implement evidence nature {nature!r}") from exc


def lagen_nu_descriptor(evidence_nature: str) -> KnowledgeProviderDescriptor:
    """Stable descriptor for one implemented nature, from the shared registration."""
    mcp_source_for_nature(evidence_nature)
    return KnowledgeProviderDescriptor(
        provider_id=f"{LAGEN_NU_PROVIDER_ID}.{evidence_nature}",
        domains=frozenset({LAGEN_NU_DOMAIN}),
        modalities=frozenset({"text"}),
        capabilities=frozenset(
            {
                "search",
                "retrieve",
                "resolve_citation",
                *(("citation_graph",) if evidence_nature == "swedish_case_law" else ()),
            }
        ),
        evidence_natures=frozenset({evidence_nature}),
        authority={
            "jurisdiction": LAGEN_NU_JURISDICTION,
            "tenant_bound": False,
            "retrieval_provider": LAGEN_NU_PROVIDER_ID,
            "authority_level": "trusted",
            "primary_source": True,
            "source_nature": "primary",
            "official_source_aggregator": True,
            "publication_note": LAGEN_NU_PUBLICATION_NOTE,
            "mcp_source": _MCP_SOURCE_BY_NATURE[evidence_nature],
        },
        access=ProviderAccess(mechanism="mcp", adapter=LAGEN_NU_ADAPTER),
        rank=10,
    )


def lagen_nu_capability_descriptors() -> tuple[KnowledgeProviderDescriptor, ...]:
    return tuple(lagen_nu_descriptor(nature) for nature in LAGEN_NU_EVIDENCE_NATURES)
