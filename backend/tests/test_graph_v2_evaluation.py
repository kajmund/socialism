"""The recorded research scenario remains idempotent in Graph v2."""

from scripts.evaluate_graph_v2 import evaluate


async def test_recorded_36_avtl_graph_projection():
    result = await evaluate()
    assert result["first_pass"] == {"nodes": 10, "facts": 7, "provenance": 7}
    assert result["growth_on_replay"] == {"nodes": 0, "facts": 0, "provenance": 0}
    assert result["lexical_recall_at_3"]["hits"] >= 6
    assert result["positive_case_three_facts_reachable_in_two_hops"]
    assert result["other_tenant_hits"] == 0
