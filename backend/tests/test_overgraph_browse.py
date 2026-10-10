"""Admin browse pages over a temporary OverGraph catalog."""

from app.services.overgraph.browse import catalog_summary, list_nodes, node_detail
from app.services.overgraph.catalogs import open_catalog

DIM = 4


def _catalog(tmp_path):
    return open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)


def test_browse_lists_labels_nodes_and_edges(tmp_path):
    catalog = _catalog(tmp_path)
    try:
        fact = catalog.upsert_node(
            ["Fact", "scope.shared"],
            "alpha",
            props={"text": "lagen om anställning", "embedding": [float(i) for i in range(20)]},
            dense_vector=[0.1, 0.2, 0.3, 0.4],
        )
        entity = catalog.upsert_node(["Entity"], "person-1", props={"name": "Ada"})
        catalog.upsert_edge(fact, entity, "SUBJECT", props={"note": "ämne"})
        summary = catalog_summary(catalog)
        counts = {row["label"]: row["count"] for row in summary["node_labels"]}
        assert counts["Fact"] == 1
        assert counts["scope.shared"] == 1
        assert summary["edge_labels"] == [{"label": "SUBJECT", "count": 1}]

        page = list_nodes(catalog, label="Fact", query="", limit=10, after=None)
        assert page["next_cursor"] is None
        assert page["nodes"][0]["key"] == "alpha"
        assert page["nodes"][0]["preview"] == "lagen om anställning"

        found = list_nodes(catalog, label="Fact", query="lagen", limit=10, after=None)
        assert [row["key"] for row in found["nodes"]] == ["alpha"]
        missed = list_nodes(catalog, label="Fact", query="ada", limit=10, after=None)
        assert missed["nodes"] == []

        detail = node_detail(catalog, fact)
        assert detail is not None
        assert detail["props"]["text"] == "lagen om anställning"
        assert detail["props"]["embedding"] == "[20 values]"
        assert "dense_vector" not in detail
        edge = detail["edges"][0]
        assert edge["direction"] == "outgoing"
        assert edge["label"] == "SUBJECT"
        assert edge["valid_to"] is None
        assert edge["props"] == {"note": "ämne"}
        assert edge["node"]["id"] == entity
        assert edge["node"]["preview"] == "Ada"
        incoming = node_detail(catalog, entity)
        assert incoming is not None
        assert incoming["edges"][0]["direction"] == "incoming"
        assert node_detail(catalog, 999) is None
        memory = catalog.upsert_node(
            ["Memory"],
            "mem-1",
            props={
                "agent_id": "expert:ada",
                "payload_json": '{"data":"minns ett möte","user_id":"kund:1"}',
            },
        )
        remembered = list_nodes(catalog, label="Memory", query="möte", limit=10, after=None)
        assert remembered["nodes"][0]["id"] == memory
        assert remembered["nodes"][0]["preview"] == "minns ett möte"
        memory_detail = node_detail(catalog, memory)
        assert memory_detail is not None
        assert memory_detail["props"]["payload_json"]["data"] == "minns ett möte"
    finally:
        catalog.close()


def test_browse_search_cursor_continues_after_a_full_page(tmp_path):
    catalog = _catalog(tmp_path)
    try:
        for index in range(5):
            catalog.upsert_node(["Fact"], f"k{index}", props={"text": f"row {index}"})
        first = list_nodes(catalog, label="Fact", query="row", limit=2, after=None)
        assert [row["key"] for row in first["nodes"]] == ["k0", "k1"]
        assert first["next_cursor"] is not None
        second = list_nodes(
            catalog, label="Fact", query="row", limit=2, after=first["next_cursor"],
        )
        assert [row["key"] for row in second["nodes"]] == ["k2", "k3"]
        third = list_nodes(
            catalog, label="Fact", query="row", limit=2, after=second["next_cursor"],
        )
        assert [row["key"] for row in third["nodes"]] == ["k4"]
        assert third["next_cursor"] is None
    finally:
        catalog.close()
