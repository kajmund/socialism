"""Process-owned tenant catalogs for the backend graph loop."""

from app.config import settings
from app.services.document_qa.tenants import TenantCatalogs, set_tenant_catalogs
from app.services.overgraph.catalogs import catalog_root


def attach_graph_owner() -> TenantCatalogs:
    catalogs = TenantCatalogs(
        catalog_root(settings.overgraph_dir),
        dimension=settings.embedding_dimension,
    )
    set_tenant_catalogs(catalogs)
    return catalogs


def detach_graph_owner() -> None:
    set_tenant_catalogs(None)
