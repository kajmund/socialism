"""Owner routing keeps catalog kinds and tenants isolated."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner import OvergraphOwner
from app.services.overgraph.owner_registry import (
    OwnerRegistry,
    OwnerRoute,
    parse_tenant_owner_sockets,
)

DIMENSION = 4
NODE = {"labels": ["Entity", "scope.customer.1"], "key": "same-key",
        "props": {"scope_key": "customer:1", "value": "x"}}


async def test_registry_routes_each_catalog_to_its_own_owner():
    root = Path(tempfile.mkdtemp(prefix="owner-registry-"))
    owners = []
    routes = []
    for kind, customer in (("knowledge", None), ("tenant_knowledge", 1),
                           ("tenant_knowledge", 2), ("memory", None)):
        label = f"{kind}-{customer}" if customer else kind
        catalog = open_catalog(root / label, kind="knowledge" if "knowledge" in kind else "memory",
                               dimension=DIMENSION)
        owner = OvergraphOwner(
            root / label, dimension=DIMENSION, socket_path=root / f"{label}.sock",
            catalog=catalog,
        )
        await owner.start()
        owners.append(owner)
        routes.append(OwnerRoute(kind=kind, socket_path=owner.socket_path, customer_id=customer))
    registry = OwnerRegistry()
    try:
        await registry.connect(routes)
        assert (await registry.health()) == {
            "knowledge:shared": True, "tenant_knowledge:1": True,
            "tenant_knowledge:2": True, "memory:shared": True,
        }
        for kind, customer in (("knowledge", None), ("tenant_knowledge", 1),
                               ("tenant_knowledge", 2), ("memory", None)):
            client = registry.client_for(kind, customer_id=customer)
            await client.mutate(f"write-{kind}-{customer}", {"upsert_nodes": [NODE]}, kind="batch")
        for kind, customer in (("knowledge", None), ("tenant_knowledge", 1),
                               ("tenant_knowledge", 2), ("memory", None)):
            client = registry.client_for(kind, customer_id=customer)
            response = await client.read([{"label": "Entity", "key": "same-key"}])
            assert response["values"]["Entity:same-key"]["value"] == "x"
        # The same key in tenant 1 and 2 is two independent catalogs.
        t1 = registry.client_for("tenant_knowledge", customer_id=1)
        t2 = registry.client_for("tenant_knowledge", customer_id=2)
        await t1.mutate("change-t1", {"upsert_nodes": [{
            "labels": ["Entity", "scope.customer.1"], "key": "same-key",
            "props": {"scope_key": "customer:1", "value": "t1"},
        }]}, kind="batch")
        assert (await t1.read([{"label": "Entity", "key": "same-key"}]))["values"]["Entity:same-key"]["value"] == "t1"
        assert (await t2.read([{"label": "Entity", "key": "same-key"}]))["values"]["Entity:same-key"]["value"] == "x"
    finally:
        await registry.close()
        for owner in owners:
            await owner.close()


def test_parse_tenant_owner_sockets_returns_verified_routes():
    routes = parse_tenant_owner_sockets(
        "1=/run/tenant-1.sock, 2 = /run/tenant-2.sock ,"
    )
    assert [(route.kind, route.customer_id, str(route.socket_path)) for route in routes] == [
        ("tenant_knowledge", 1, "/run/tenant-1.sock"),
        ("tenant_knowledge", 2, "/run/tenant-2.sock"),
    ]
    assert parse_tenant_owner_sockets("") == []
    assert parse_tenant_owner_sockets(" , ") == []


def test_parse_tenant_owner_sockets_rejects_invalid_config():
    for raw in ("1", "1=", "=/run/a.sock", "x=/run/a.sock", "0=/run/a.sock",
                "1=/a.sock,1=/b.sock"):
        try:
            parse_tenant_owner_sockets(raw)
        except ValueError:
            continue
        raise AssertionError(f"invalid tenant owner config accepted: {raw!r}")
