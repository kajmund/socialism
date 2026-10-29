from app.services.tabular_review.benchmark import run_scripted_table


def test_scripted_200_document_table_recalls_golden_hits():
    payload = run_scripted_table(document_count=200, columns=("uppsagning", "pris"))
    assert payload["kind"] == "scripted"
    assert payload["not_live_model_quality"] is True
    assert payload["documents"] == 200
    assert payload["cells"] == 400
    assert payload["recall"] == 1.0
    assert payload["first_table_seconds"] < 1.0
    assert payload["ssr_seconds"] < 2.0
    assert payload["no_hit"] == 300
