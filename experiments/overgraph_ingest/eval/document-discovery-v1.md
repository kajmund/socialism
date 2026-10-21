# Document discovery v1

Model-free diagnostic. Ranks documents by aggregating their TextUnit dense scores instead of ranking TextUnits directly. Production is unchanged; this is not a new retriever.

Equal budget: hybrid top-50 TextUnits vs 10 documents x 5 units.

## DocumentRecall at equal budget (10 documents)

| Arm | Recall@10 docs | New vs hybrid50 | CompleteEvidence@5 |
|---|---:|---:|---:|
| dense_top1 | 0.3759 | 0 | 0.9861 |
| dense_top3_sum | 0.4187 | 1 | 0.9877 |
| dense_top3_mean | 0.4187 | 1 | 0.9877 |
| dense_top5_sum | 0.3999 | 2 | 0.9877 |
| dense_top5_mean | 0.3999 | 2 | 0.9877 |

| Baseline | Recall | Found docs | Units examined |
|---|---:|---:|---:|
| hybrid_units_20 | 0.5966 | 80 | 180 |
| hybrid_units_50 | 0.8554 | 130 | 450 |
| dense_units_20 | 0.5424 | 76 | 180 |
| dense_units_50 | 0.8227 | 131 | 450 |

## Recall by document budget

| Arm | @10 | @20 | @50 |
|---|---:|---:|---:|
| dense_top1 | 0.3759 | 0.5901 | 0.9174 |
| dense_top3_sum | 0.4187 | 0.5930 | 0.9060 |
| dense_top3_mean | 0.4187 | 0.5930 | 0.9060 |
| dense_top5_sum | 0.3999 | 0.6208 | 0.9014 |
| dense_top5_mean | 0.3999 | 0.6208 | 0.9014 |

## Limitations

- The discovery signal still uses the same dense embedding; only the aggregation changes. A ceiling that does not move means the signal, not the aggregation, is the bottleneck.
- Equal-budget comparison is 50 examined TextUnits: hybrid top-50 versus 10 documents x 5 units.
- DocumentRecall is measured against documents that have passage gold.
