# Tantivy BM25 v1

Experimental comparison. Production retrieval is unchanged.
Status: **completed**.
Claim scope: **improved_retrieval_only**.

## Verdict

```json
{
  "verdict": "mixed",
  "production_changed": false,
  "default_retriever_unchanged": true,
  "claim_scope": "improved_retrieval_only",
  "holdout_status": "not_blind",
  "generalisation_status": "insufficient",
  "dense_bm25_document_recall_at_20": 0.49576516076516075,
  "hybrid_current_document_recall_at_20": 0.5697069597069597,
  "dense_document_recall_at_20": 0.39691900691900694,
  "dense_bm25_document_recall_at_50": 0.7125742775742776,
  "dense_document_recall_at_50": 0.693078958078958,
  "dense_bm25_vs_dense_delta_at_20": 0.09884615384615385,
  "dense_bm25_vs_hybrid_delta_at_20": -0.07394179894179896,
  "complete_evidence_delta_at_5": -0.25,
  "control_and_positive_identical": true,
  "critical_case_review_required": true
}
```

## Global macro

| Profil | Arm | DocumentRecall@20 | EvidenceRecall@20 | NDCG@20 | Precision@20 | HN@20 | DocumentRecall@50 |
|---|---|---:|---:|---:|---:|---:|---:|
| sv_stem_v1 | dense | 0.3969 | 0.3834 | 0.4612 | 0.2889 | 0.4444 | 0.6931 |
| sv_stem_v1 | sparse | 0.2875 | 0.2667 | 0.2812 | 0.1667 | 0.2222 | 0.5192 |
| sv_stem_v1 | hybrid_current | 0.5697 | 0.5467 | 0.5531 | 0.3667 | 0.4444 | 0.7595 |
| sv_stem_v1 | hybrid_rrf_control | 0.5712 | 0.5482 | 0.5826 | 0.3722 | 0.4444 | 0.7618 |
| sv_stem_v1 | hybrid_rrf_positive | 0.5712 | 0.5482 | 0.5826 | 0.3722 | 0.4444 | 0.7618 |
| sv_stem_v1 | bm25 | 0.2832 | 0.2602 | 0.3061 | 0.1778 | 0.2222 | 0.3863 |
| sv_stem_v1 | dense_bm25 | 0.4958 | 0.4741 | 0.4560 | 0.3000 | 0.4444 | 0.7126 |
| sv_plain_v1 | dense | 0.3969 | 0.3834 | 0.4612 | 0.2889 | 0.4444 | 0.6931 |
| sv_plain_v1 | sparse | 0.2875 | 0.2667 | 0.2812 | 0.1667 | 0.2222 | 0.5192 |
| sv_plain_v1 | hybrid_current | 0.5697 | 0.5467 | 0.5531 | 0.3667 | 0.4444 | 0.7595 |
| sv_plain_v1 | hybrid_rrf_control | 0.5712 | 0.5482 | 0.5826 | 0.3722 | 0.4444 | 0.7618 |
| sv_plain_v1 | hybrid_rrf_positive | 0.5712 | 0.5482 | 0.5826 | 0.3722 | 0.4444 | 0.7618 |
| sv_plain_v1 | bm25 | 0.2719 | 0.2524 | 0.2909 | 0.1556 | 0.1111 | 0.3921 |
| sv_plain_v1 | dense_bm25 | 0.5012 | 0.4841 | 0.4598 | 0.3000 | 0.3333 | 0.7065 |

## Document-local macro

| Profil | Arm | CompleteEvidence@5 | Hit@5 | NDCG@5 | MRR@5 |
|---|---|---:|---:|---:|---:|
| sv_stem_v1 | dense | 0.9870 | 0.9870 | 0.8187 | 0.7797 |
| sv_stem_v1 | sparse | 0.5584 | 0.5714 | 0.4294 | 0.4087 |
| sv_stem_v1 | hybrid_current | 0.6753 | 0.6883 | 0.5858 | 0.5760 |
| sv_stem_v1 | hybrid_rrf_control | 0.6753 | 0.6883 | 0.5858 | 0.5760 |
| sv_stem_v1 | hybrid_rrf_positive | 0.8052 | 0.8182 | 0.6422 | 0.6084 |
| sv_stem_v1 | bm25 | 0.5195 | 0.5325 | 0.4153 | 0.4030 |
| sv_stem_v1 | dense_bm25 | 0.7143 | 0.7273 | 0.5977 | 0.5814 |
| sv_plain_v1 | dense | 0.9870 | 0.9870 | 0.8187 | 0.7797 |
| sv_plain_v1 | sparse | 0.5584 | 0.5714 | 0.4294 | 0.4087 |
| sv_plain_v1 | hybrid_current | 0.6753 | 0.6883 | 0.5858 | 0.5760 |
| sv_plain_v1 | hybrid_rrf_control | 0.6753 | 0.6883 | 0.5858 | 0.5760 |
| sv_plain_v1 | hybrid_rrf_positive | 0.8052 | 0.8182 | 0.6422 | 0.6084 |
| sv_plain_v1 | bm25 | 0.4675 | 0.4805 | 0.3734 | 0.3641 |
| sv_plain_v1 | dense_bm25 | 0.6883 | 0.7013 | 0.5711 | 0.5548 |

## Twenty versus fifty

| Gold | Required | Applicable | Ceiling@20 | DenseBM25 R@20 | Hybrid R@50 | Dense R@50 |
|---|---:|---|---:|---:|---:|---:|
| auto-renewal | 20 | True | 20 | 0.2500 | 1.0000 | 0.8000 |
| notice-period | 13 | True | 13 | 0.7692 | 0.8462 | 0.6923 |
| liability-cap | 34 | False | 20 | 0.5000 | 0.8929 | 0.7143 |
| confidentiality | 13 | True | 13 | 0.1538 | 0.4615 | 0.6923 |
| liability-secrecy-carveout | 8 | True | 8 | 0.8571 | 1.0000 | 0.8571 |
| governing-law | 75 | False | 20 | 0.0400 | 0.1600 | 0.5067 |
| force-majeure | 5 | True | 5 | 1.0000 | 1.0000 | 1.0000 |
| personal-data | 15 | True | 15 | 0.2667 | 0.6000 | 0.6000 |
| assignment | 8 | True | 8 | 0.6250 | 0.8750 | 0.3750 |

## Coverage depth

| Gold | DenseBM25 K90 | DenseBM25 K100 | DenseBM25 K90 complete | DenseBM25 K100 complete |
|---|---:|---:|---:|---:|
| auto-renewal | 148 | not_reached | 148 | not_reached |
| notice-period | 152 | 160 | 152 | 160 |
| liability-cap | 86 | not_reached | 86 | not_reached |
| confidentiality | 141 | 160 | 141 | 160 |
| liability-secrecy-carveout | not_reached | not_reached | not_reached | not_reached |
| governing-law | 191 | not_reached | 191 | not_reached |
| force-majeure | 19 | 19 | 19 | 19 |
| personal-data | not_reached | not_reached | not_reached | not_reached |
| assignment | not_reached | not_reached | not_reached | not_reached |

## Additions and displacements

| Gold | Added relevant | Displaced relevant |
|---|---:|---:|
| auto-renewal | 0 | 5 |
| notice-period | 9 | 0 |
| liability-cap | 6 | 0 |
| confidentiality | 0 | 4 |
| liability-secrecy-carveout | 2 | 0 |
| governing-law | 0 | 9 |
| force-majeure | 0 | 0 |
| personal-data | 1 | 1 |
| assignment | 3 | 0 |

## Per-query global

| Gold | Required | DenseBM25 R@20 | Hybrid R@20 | Dense R@20 | DenseBM25 R@50 | Dense R@50 |
|---|---:|---:|---:|---:|---:|---:|
| auto-renewal | 20 | 0.2500 | 0.7500 | 0.5000 | 0.6000 | 0.8000 |
| notice-period | 13 | 0.7692 | 0.7692 | 0.0769 | 0.7692 | 0.6923 |
| liability-cap | 34 | 0.5000 | 0.4643 | 0.2857 | 0.8571 | 0.7143 |
| confidentiality | 13 | 0.1538 | 0.1538 | 0.4615 | 0.5385 | 0.6923 |
| liability-secrecy-carveout | 8 | 0.8571 | 1.0000 | 0.5714 | 1.0000 | 0.8571 |
| governing-law | 75 | 0.0400 | 0.0400 | 0.1600 | 0.1733 | 0.5067 |
| force-majeure | 5 | 1.0000 | 0.8000 | 1.0000 | 1.0000 | 1.0000 |
| personal-data | 15 | 0.2667 | 0.4000 | 0.2667 | 0.6000 | 0.6000 |
| assignment | 8 | 0.6250 | 0.7500 | 0.2500 | 0.8750 | 0.3750 |

## Per-question document-local

| Fråga | Split | DenseBM25 CE@5 | Hybrid CE@5 | Dense CE@5 | Positive control CE@5 |
|---|---|---:|---:|---:|---:|
| auto-renewal | development | 0.8333 | 0.7500 | 0.8333 | 0.8333 |
| auto-renewal | locked_holdout | 0.8571 | 0.8571 | 0.8571 | 0.8571 |
| confidentiality | development | 0.5385 | 0.3846 | 1.0000 | 0.6154 |
| confidentiality | locked_holdout | 0.4444 | 0.1111 | 1.0000 | 0.2222 |
| liability-cap | development | 0.5000 | 0.8333 | 1.0000 | 1.0000 |
| liability-cap | locked_holdout | 0.4444 | 0.6667 | 1.0000 | 1.0000 |
| liability-secrecy-carveout | development | 0.6667 | 0.6667 | 1.0000 | 0.6667 |
| liability-secrecy-carveout | locked_holdout | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| notice-period | development | 1.0000 | 0.9286 | 1.0000 | 1.0000 |
| notice-period | locked_holdout | 0.9000 | 0.9000 | 1.0000 | 0.9000 |

## Uncertainty

```json
{
  "global": {
    "dense_bm25_vs_dense_document_recall20": {
      "status": "estimated",
      "n_observations": 9,
      "n_clusters": 9,
      "mean_delta": 0.09756552380952381,
      "ci95": [
        -0.09462759462759464,
        0.30128205128205127
      ],
      "iterations": 10000,
      "seed": 0,
      "cluster_unit": "gold"
    },
    "dense_bm25_vs_hybrid_document_recall20": {
      "status": "estimated",
      "n_observations": 9,
      "n_clusters": 9,
      "mean_delta": -0.07339632275132277,
      "ci95": [
        -0.20277777777777778,
        0.03452380952380951
      ],
      "iterations": 10000,
      "seed": 0,
      "cluster_unit": "gold"
    }
  },
  "document": {
    "dense_bm25_vs_dense_complete5": {
      "status": "estimated",
      "n_observations": 77,
      "n_clusters": 32,
      "mean_delta": -0.2728497413411964,
      "ci95": [
        -0.359375,
        -0.1917808219178082
      ],
      "iterations": 10000,
      "seed": 0,
      "cluster_unit": "document"
    },
    "dense_bm25_vs_hybrid_complete5": {
      "status": "estimated",
      "n_observations": 77,
      "n_clusters": 32,
      "mean_delta": 0.040023468417207414,
      "ci95": [
        -0.06172839506172839,
        0.14606741573033707
      ],
      "iterations": 10000,
      "seed": 0,
      "cluster_unit": "document"
    }
  }
}
```

## Control

Control and positive sparse arms identical at k=20 globally: **True**.
Historical hybrid differs from the locked RRF control at k=20: **True**. Historical OverGraph reciprocal_rank contract; not rewritten.
Global zero-score sparse hits: `{"auto-renewal": 0, "notice-period": 0, "liability-cap": 0, "confidentiality": 0, "liability-secrecy-carveout": 0, "governing-law": 0, "force-majeure": 0, "personal-data": 0, "assignment": 0}`
Document-locally the positive sparse control differs: compare hybrid_rrf_positive and hybrid_rrf_control in the macro table. That gain is not attributable to BM25.

## Latency

| Profil | Stage | p50 s | p95 s |
|---|---|---:|---:|
| sv_stem_v1 | query_analysis | 0.0000 | 0.0000 |
| sv_stem_v1 | dense_engine | 0.0117 | 0.0123 |
| sv_stem_v1 | sparse_engine | 0.0003 | 0.0004 |
| sv_stem_v1 | bm25 | 0.0010 | 0.0012 |
| sv_stem_v1 | fusion | 0.0002 | 0.0002 |
| sv_stem_v1 | hydrate | 0.0001 | 0.0001 |
| sv_stem_v1 | query_encode_seconds | 0.2488 | 0.6156 |
| sv_stem_v1 | retrieval_seconds | 0.0136 | 0.0139 |
| sv_stem_v1 | end_to_end_seconds | 0.2621 | 0.6287 |
| sv_plain_v1 | query_analysis | 0.0000 | 0.0000 |
| sv_plain_v1 | dense_engine | 0.0117 | 0.0124 |
| sv_plain_v1 | sparse_engine | 0.0003 | 0.0004 |
| sv_plain_v1 | bm25 | 0.0021 | 0.0024 |
| sv_plain_v1 | fusion | 0.0002 | 0.0002 |
| sv_plain_v1 | hydrate | 0.0001 | 0.0001 |
| sv_plain_v1 | query_encode_seconds | 0.2488 | 0.6156 |
| sv_plain_v1 | retrieval_seconds | 0.0141 | 0.0165 |
| sv_plain_v1 | end_to_end_seconds | 0.2642 | 0.6295 |

Python document-local ranking is reported separately from Tantivy/OverGraph latency.

## Paging and answer test

Paging: **completed**, page size 20.
Answer test: **not_run**. Without a completed answer test the claim remains improved retrieval only.

## Error analysis

Full candidate lists, branch ranks/scores, additions/displacements, and per-cell misses are in the run JSON. This report shows the macro and per-query decision layer only.

## Limitations

- The Swedish Tantivy stemmer maps förlängs to förläng but leaves förlängning unchanged; the result is pipeline-level, not a pure BM25 formula test.
- HOLD_OUT_CELLS is locked but not blind: it was used for the tabular holdout. Generalisation is insufficient without a new independent corpus.
- OverGraph vector_search has no property filter; document-local dense/sparse arms use Python ranking and must not be reported as engine latency.
- Governing-law has 75 relevant documents, so full coverage at 20 is mathematically impossible and is marked not_applicable.
- The experiment does not change production retrieval, add a router, or tune BM25 parameters.
