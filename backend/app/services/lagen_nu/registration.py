"""One production registration for the official lagen.nu KnowledgeProvider."""

from __future__ import annotations

from app.services.research.models import ResearchSourceType
from app.services.research.provider import KnowledgeProviderDescriptor, ProviderAccess

LAGEN_NU_PROVIDER_ID = "lagen_nu"
LAGEN_NU_ADAPTER = "lagen_nu_research_source"
LAGEN_NU_DOMAIN = "law"
LAGEN_NU_JURISDICTION = "SE"
LAGEN_NU_AUTHORITY_WARNING = (
    "lagen.nu automated material can contain errors and is not an official publication"
)
LAGEN_NU_EVIDENCE_NATURES: tuple[ResearchSourceType, ...] = (
    "swedish_law",
    "swedish_preparatory_works",
)
_MCP_SOURCE_BY_NATURE: dict[str, str] = {
    "swedish_law": "sfs",
    "swedish_preparatory_works": "forarbete",
}


def mcp_source_for_nature(nature: str) -> str:
    try:
        return _MCP_SOURCE_BY_NATURE[nature]
    except KeyError as exc:
        raise ValueError(f"lagen.nu adapter does not implement evidence nature {nature!r}") from exc


def lagen_nu_descriptor(evidence_nature: ResearchSourceType) -> KnowledgeProviderDescriptor:
    """Stable descriptor for one implemented nature, from the shared registration."""
    mcp_source_for_nature(evidence_nature)
    return KnowledgeProviderDescriptor(
        provider_id=f"{LAGEN_NU_PROVIDER_ID}.{evidence_nature}",
        domains=frozenset({LAGEN_NU_DOMAIN}),
        modalities=frozenset({"text"}),
        capabilities=frozenset({"search", "retrieve", "resolve_citation"}),
        evidence_natures=frozenset({evidence_nature}),
        authority={
            "jurisdiction": LAGEN_NU_JURISDICTION,
            "tenant_bound": False,
            "retrieval_provider": LAGEN_NU_PROVIDER_ID,
            "automated_corpus": True,
            "not_official_publication": True,
            "authority_warning": LAGEN_NU_AUTHORITY_WARNING,
            "mcp_source": _MCP_SOURCE_BY_NATURE[evidence_nature],
        },
        access=ProviderAccess(mechanism="mcp", adapter=LAGEN_NU_ADAPTER),
        rank=10,
    )


def lagen_nu_capability_descriptors() -> tuple[KnowledgeProviderDescriptor, ...]:
    return tuple(lagen_nu_descriptor(nature) for nature in LAGEN_NU_EVIDENCE_NATURES)
