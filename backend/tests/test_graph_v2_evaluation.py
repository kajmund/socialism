"""The recorded research scenario remains idempotent in Graph v2."""

from scripts.evaluate_graph_v2 import evaluate


async def test_recorded_36_avtl_graph_projection():
    result = await evaluate()
    assert result["first_pass"] == {"nodes": 12, "facts": 9, "provenance": 9}
    assert result["growth_on_replay"] == {"nodes": 0, "facts": 0, "provenance": 0}
    assert result["lexical_recall_at_3"]["hits"] >= 6
    assert result["cross_source_two_hop"]
    assert result["shared_consumer_protection_value"]
    assert result["multi_hop_path"]["hops"] == 2
    assert "legal.consumer_protection.value" in result["multi_hop_path"]["via"]
    assert result["multi_hop_path"]["from"] != result["multi_hop_path"]["to"]
    assert result["other_tenant_hits"] == 0
