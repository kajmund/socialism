from pathlib import Path

import pytest

from overgraph_ingest.coverage.blind_carveout import GOLD_ZIP
from overgraph_ingest.coverage.blind_gold import load_blind_property


@pytest.mark.skipif(not GOLD_ZIP.is_file(), reason="blind gold zip is not in the checkout")
def test_blind_carveout_gold_keeps_uncertain_out_of_relevant() -> None:
    gold, classes, traps = load_blind_property("E_sekretessundantag_fran_ansvarsbegransning")
    assert gold.id == "liability-secrecy-carveout"
    assert gold.proof_kind == "COMPOSITE"
    assert gold.coverage_groups == []
    assert len(gold.relevant_documents) == 53
    assert sum(1 for label in classes.values() if label == "YES") == 53
    assert sum(1 for label in classes.values() if label == "NO") == 39
    assert sum(1 for label in classes.values() if label == "UNCERTAIN") == 8
    assert "avtal_101.docx" not in gold.relevant_documents
    assert traps["avtal_101.docx"] == "co_occurrence_without_relation"
    assert Path(gold.relevant_documents[0]).suffix == ".docx"
