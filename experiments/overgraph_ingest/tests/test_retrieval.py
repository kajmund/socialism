from pathlib import Path

import pytest

from overgraph_ingest.benchmarks.corpus import write_retrieval_corpus
from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.extraction import extract_file
from overgraph_ingest.ids import hash_file
from overgraph_ingest.retrieval.encode import HashedDenseEncoder, LexicalSparseEncoder, tokenize
from overgraph_ingest.segmentation.structural import segment_document
from overgraph_ingest.retrieval.evaluate import evaluate_strategy, judge_units, ndcg
from overgraph_ingest.retrieval.gold import RetrievalGold, GoldSpan, load_retrieval_gold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.run import run_retrieval
from overgraph_ingest.retrieval.search import SearchHit, rrf_fuse, union_pool
from tests.conftest import ingest, make_config

OFFICIAL_GOLD = (
    Path(__file__).resolve().parents[1] / "retrieval_gold" / "auto-renewal.json"
)
EXTRA_CORPUS = Path(__file__).resolve().parents[1] / "data" / "extra_corpus"


def test_stemmer_collapses_renewal_variants() -> None:
    assert "förläng" in tokenize("förlängning")
    assert "förläng" in tokenize("förlängs automatiskt")
    assert tokenize("förlängning")[0] == tokenize("förlängs")[0]


def test_official_auto_renewal_gold_lists_twenty_contracts() -> None:
    gold = load_retrieval_gold(OFFICIAL_GOLD)
    assert gold.query.startswith("Vilka avtal")
    assert len(gold.relevant_documents) == 20
    assert gold.hard_negatives[0].relative_path.startswith("Avtal_15_")


@pytest.mark.skipif(not EXTRA_CORPUS.is_dir(), reason="extra_corpus is not present")
def test_official_gold_spans_exist_in_extra_corpus() -> None:
    gold = load_retrieval_gold(OFFICIAL_GOLD)
    missing = []
    for span in [*gold.relevant_units, *gold.hard_negatives]:
        path = EXTRA_CORPUS / span.relative_path
        extracted = extract_file(
            path.read_bytes(),
            path.name,
            hash_file(path),
            extraction_version="extract-v1",
        )
        segmented = segment_document(
            extracted,
            document_version_id="gold",
            segmentation_version="structural-v1",
        )
        if not any(span.contains in unit.text for unit in segmented.units):
            missing.append(span.relative_path)
    assert missing == []


def test_absent_span_is_not_confused_with_low_rank() -> None:
    gold = RetrievalGold(
        id="t",
        query="automatisk förlängning",
        relevant_units=[
            GoldSpan("a.docx", "förlängs automatiskt"),
            GoldSpan("missing.docx", "finns inte"),
        ],
        hard_negatives=[],
    )
    units = [
        StoredUnit(1, "u1", "d1", "a.docx", "Avtalet förlängs automatiskt.", None, None),
    ]
    relevant, _negatives, absent = judge_units(units, gold)
    assert relevant == {"u1"}
    assert [item.relative_path for item in absent] == ["missing.docx"]
    hits = [
        SearchHit(1, "u1", 1.0, 1, "d1", "a.docx", units[0].text),
        SearchHit(2, "other", 0.1, 2, "d2", "b.docx", "annat"),
    ]
    metrics = evaluate_strategy(
        mode="sparse",
        k=1,
        gold=gold,
        hits=hits,
        exhaustive=hits,
        relevant_keys=relevant,
        negative_keys=set(),
        absent=absent,
    )
    assert metrics.recall == 1.0
    assert metrics.document_coverage == 0.5
    assert metrics.absent[0].relative_path == "missing.docx"


def test_low_rank_is_separated_from_unretrieved() -> None:
    gold = RetrievalGold(
        id="t",
        query="q",
        relevant_units=[GoldSpan("a.docx", "rätt")],
        hard_negatives=[],
    )
    hits = [
        SearchHit(2, "noise-a", 0.9, 1, "d2", "b.docx", "annat"),
        SearchHit(3, "noise-b", 0.8, 2, "d3", "c.docx", "annat"),
        SearchHit(1, "u1", 0.2, 3, "d1", "a.docx", "rätt klausul"),
    ]
    exhaustive = [
        SearchHit(1, "u1", 0.9, 1, "d1", "a.docx", "rätt klausul"),
        SearchHit(2, "noise-a", 0.1, 2, "d2", "b.docx", "annat"),
        SearchHit(3, "noise-b", 0.05, 3, "d3", "c.docx", "annat"),
    ]
    metrics = evaluate_strategy(
        mode="dense",
        k=2,
        gold=gold,
        hits=hits,
        exhaustive=exhaustive,
        relevant_keys={"u1"},
        negative_keys=set(),
        absent=[],
    )
    assert metrics.recall == 0.0
    assert metrics.mrr == 0.0
    assert metrics.ndcg == 0.0
    assert [item.kind for item in metrics.low_rank] == ["low_rank"]
    assert metrics.unretrieved == []


def test_mrr_and_ndcg_reward_earlier_relevant_hits() -> None:
    gold = RetrievalGold(
        id="t",
        query="q",
        relevant_units=[GoldSpan("a.docx", "rätt")],
        hard_negatives=[GoldSpan("n.docx", "inte")],
    )
    late = [
        SearchHit(2, "neg", 0.9, 1, "d2", "n.docx", "inte"),
        SearchHit(3, "noise", 0.8, 2, "d3", "c.docx", "annat"),
        SearchHit(1, "u1", 0.2, 3, "d1", "a.docx", "rätt"),
    ]
    early = [
        SearchHit(1, "u1", 0.9, 1, "d1", "a.docx", "rätt"),
        SearchHit(2, "neg", 0.2, 2, "d2", "n.docx", "inte"),
    ]
    late_metrics = evaluate_strategy(
        mode="dense",
        k=3,
        gold=gold,
        hits=late,
        exhaustive=late,
        relevant_keys={"u1"},
        negative_keys={"neg"},
        absent=[],
    )
    early_metrics = evaluate_strategy(
        mode="dense",
        k=3,
        gold=gold,
        hits=early,
        exhaustive=early,
        relevant_keys={"u1"},
        negative_keys={"neg"},
        absent=[],
    )
    assert late_metrics.mrr == pytest.approx(1 / 3)
    assert early_metrics.mrr == 1.0
    assert early_metrics.ndcg > late_metrics.ndcg
    assert late_metrics.hard_negative_ranks[0]["rank"] == 1
    assert late_metrics.unique_documents == 3
    assert ndcg([1.0, 0.0], relevant_count=1) == 1.0


def test_tfidf_downweights_corpus_wide_terms() -> None:
    encoder = LexicalSparseEncoder()
    encoder.fit(
        [
            "Avtalet gäller tills vidare.",
            "Avtalet gäller i tolv månader.",
            "Avtalet förlängs automatiskt med samma period.",
        ]
    )
    query = dict(encoder.embed(["automatisk förlängning"])[0])
    renewal = dict(encoder.embed(["Avtalet förlängs automatiskt med samma period."])[0])
    generic = dict(encoder.embed(["Avtalet gäller tills vidare."])[0])
    renewal_score = sum(query.get(index, 0.0) * weight for index, weight in renewal.items())
    generic_score = sum(query.get(index, 0.0) * weight for index, weight in generic.items())
    assert renewal_score > generic_score


def test_hashed_dense_is_deterministic() -> None:
    encoder = HashedDenseEncoder(8)
    first = encoder.embed(["förlängs automatiskt"])[0]
    second = encoder.embed(["förlängs automatiskt"])[0]
    assert first == second
    assert len(first) == 8


def test_explicit_document_gold_is_used_for_coverage() -> None:
    gold = RetrievalGold(
        id="t",
        query="q",
        relevant_units=[GoldSpan("a.docx", "rätt")],
        hard_negatives=[],
        document_gold=("a.docx", "b.docx"),
    )
    assert gold.passage_documents == ["a.docx"]
    assert gold.relevant_documents == ["a.docx", "b.docx"]
    hits = [SearchHit(1, "u1", 1.0, 1, "d1", "a.docx", "rätt")]
    metrics = evaluate_strategy(
        mode="dense",
        k=1,
        gold=gold,
        hits=hits,
        exhaustive=hits,
        relevant_keys={"u1"},
        negative_keys=set(),
        absent=[],
    )
    assert metrics.recall == 1.0
    assert metrics.document_coverage == 0.5


def test_rrf_union_keeps_overlap_and_respects_budget() -> None:
    dense = [
        SearchHit(1, "a", 0.9, 1, "d1", "a.docx", "cap"),
        SearchHit(2, "b", 0.8, 2, "d2", "b.docx", "other"),
        SearchHit(5, "e", 0.7, 3, "d5", "e.docx", "other"),
    ]
    hybrid = [
        SearchHit(3, "c", 0.9, 1, "d3", "c.docx", "secret"),
        SearchHit(1, "a", 0.8, 2, "d1", "a.docx", "cap"),
        SearchHit(4, "d", 0.1, 3, "d4", "d.docx", "other"),
    ]
    fused = rrf_fuse([dense, hybrid], k=2)
    assert [hit.key for hit in fused] == ["a", "c"]
    pool = union_pool([dense, hybrid], per_list=2)
    assert {hit.key for hit in pool} == {"a", "b", "c"}
    assert len(pool) == 3


def test_three_strategies_find_the_renewal_clause(ingest_paths, tmp_path: Path) -> None:
    write_retrieval_corpus(ingest_paths["input"])
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        """
{
  "id": "test-renewal",
  "query": "Vilka avtal innehåller bestämmelser om automatisk förlängning?",
  "relevant_units": [
    {
      "relative_path": "forlangning.docx",
      "contains": "förlängs automatiskt med samma period"
    }
  ],
  "hard_negatives": [
    {
      "relative_path": "ingen_forlangning.docx",
      "contains": "förlängs inte automatiskt",
      "reason": "explicit no"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    report = ingest(ingest_paths, target_chars=2000, max_chars=4000)
    assert {item.status for item in report.outcomes} == {"PUBLISHED"}
    result = run_retrieval(
        RetrievalConfig(
            db_path=ingest_paths["db"],
            gold_path=gold_path,
            dense_dimension=8,
            write_batch_size=50,
            dense_model="hashed-dense-v1",
            embed=True,
            ks=(1, 5),
        )
    )
    payload = result.payload
    assert payload["relevant_units_in_graph"] == 1
    assert payload["absent_from_graph"] == []
    assert payload["hard_negatives_in_graph"] == 1
    for mode in ("dense", "sparse", "hybrid", "union_rrf"):
        at_five = payload["strategies"][mode]["at_k"]["5"]
        assert at_five["recall"] == 1.0
        assert at_five["document_coverage"] == 1.0
        assert at_five["mrr"] > 0
        assert at_five["ndcg"] > 0
        assert at_five["unretrieved"] == []
        labels = [hit["label"] for hit in at_five["hits"]]
        assert "relevant" in labels
        if mode != "union_rrf":
            assert "first_relevant_rank" in payload["strategies"][mode]["ranking"]
    pool = payload["strategies"]["union_pool"]["at_k"]["5"]
    assert pool["recall"] == 1.0
    assert pool["pool_size"] >= 1
    assert pool["source_k"] == 5
