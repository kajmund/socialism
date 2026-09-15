"""Official lagen.nu MCP access. Not a parallel research engine."""

from app.services.lagen_nu.mcp_client import (
    OfficialLagenNuMcpClient,
    OfficialLagenNuMcpError,
    OfficialLagenNuMcpNotFoundError,
)
from app.services.lagen_nu.models import (
    LagenNuDocument,
    LagenNuSearchHit,
    ResolvedCitations,
    SearchResults,
)
from app.services.lagen_nu.registration import (
    LAGEN_NU_ADAPTER,
    LAGEN_NU_AUTHORITY_WARNING,
    LAGEN_NU_EVIDENCE_NATURES,
    LAGEN_NU_PROVIDER_ID,
    lagen_nu_capability_descriptors,
    lagen_nu_descriptor,
    mcp_source_for_nature,
)

__all__ = [
    "LAGEN_NU_ADAPTER",
    "LAGEN_NU_AUTHORITY_WARNING",
    "LAGEN_NU_EVIDENCE_NATURES",
    "LAGEN_NU_PROVIDER_ID",
    "LagenNuDocument",
    "LagenNuSearchHit",
    "OfficialLagenNuMcpClient",
    "OfficialLagenNuMcpError",
    "OfficialLagenNuMcpNotFoundError",
    "ResolvedCitations",
    "SearchResults",
    "lagen_nu_capability_descriptors",
    "lagen_nu_descriptor",
    "mcp_source_for_nature",
]
