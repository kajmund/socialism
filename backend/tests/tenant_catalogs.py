"""Test-only tenant catalog handles backed by real in-process Owners.

Production code never opens a tenant catalog directly. Tests still need a
Catalog handle to seed and inspect the same file the Owner serves, so this
helper starts the Owner over that Catalog and exposes both.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.services.overgraph.catalogs import Catalog, open_catalog
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.overgraph.owner_registry import OwnerRegistry, OwnerRoute


class OwnerTenantCatalogs:
    def __init__(
        self,
        registry: OwnerRegistry,
        owners: dict[int, OvergraphOwner],
        roots: list[Path],
    ) -> None:
        self.registry = registry
        self.owners = owners
        self.roots = roots
        self.catalogs: dict[int, Catalog] = {
            customer_id: owner.catalog for customer_id, owner in owners.items()
        }

    def open_for(self, customer_id: int) -> Catalog:
        from app.services.document_qa.access import require_customer_id

        customer_id = require_customer_id(customer_id)
        catalog = self.catalogs.get(customer_id)
        if catalog is None:
            raise RuntimeError(f"tenant {customer_id} fixture is not started")
        return catalog

    def client_for(self, customer_id: int) -> OwnerClient:
        return self.registry.client_for("tenant_knowledge", customer_id=customer_id)

    def close(self) -> None:
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)


async def start_tenant_catalogs(
    *, dimension: int, customers: tuple[int, ...] = (1, 2),
) -> OwnerTenantCatalogs:
    registry = OwnerRegistry()
    owners: dict[int, OvergraphOwner] = {}
    roots: list[Path] = []
    for customer_id in customers:
        root = Path(tempfile.mkdtemp(prefix=f"tenant-cat-{customer_id}-"))
        catalog = open_catalog(root / "knowledge", kind="knowledge", dimension=dimension)
        owner = OvergraphOwner(
            root / "knowledge", dimension=dimension,
            socket_path=root / "owner.sock", catalog=catalog,
        )
        await owner.start()
        await registry.connect([OwnerRoute(
            kind="tenant_knowledge", socket_path=owner.socket_path,
            customer_id=customer_id,
        )])
        owners[customer_id] = owner
        roots.append(root)
    return OwnerTenantCatalogs(registry, owners, roots)


async def close_tenant_catalogs(catalogs: OwnerTenantCatalogs) -> None:
    for owner in catalogs.owners.values():
        await owner.close()
    catalogs.close()


class DirectTenantCatalogs:
    """Test-only direct opener for benchmark/integration tests.

    This is not production access: it exists so the direct strategy functions
    can be benchmarked against a Catalog without starting an Owner.
    """

    def __init__(self, root: Path, *, dimension: int) -> None:
        self.root = Path(root)
        self.dimension = dimension
        self._catalog: Catalog | None = None

    def open_for(self, customer_id: int) -> Catalog:
        from app.services.document_qa.access import require_customer_id

        require_customer_id(customer_id)
        if self._catalog is None:
            self._catalog = open_catalog(
                self.root / "knowledge", kind="knowledge", dimension=self.dimension,
            )
        return self._catalog

    def close(self) -> None:
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None


def set_tenant_catalogs(_catalogs: object) -> None:
    """Compatibility no-op for tests written before tenant Owner cutover."""
