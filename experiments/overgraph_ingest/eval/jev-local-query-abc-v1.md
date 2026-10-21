# Jev local dense query A/B/C v1

Same 50 document-property cases and stage-1 verdicts as the end-to-end run. Three arms differ only in the query text for document-local dense.

| Arm | Query | EvidenceRecall@5 (pos) | NV-pos hit | JevRecovery@5 (all NV) | NV-pos recovered | New FP errors | New SUPPORTED gold-gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | gold.query | 6/20 | 3/3 | 0/14 | 0/3 | 0 | 0 |
| B | definition | 6/20 | 3/3 | 0/14 | 0/3 | 0 | 0 |
| C | evidence description | 6/20 | 3/3 | 0/14 | 0/3 | 0 | 0 |

## Groups

```json
{
  "positive": 20,
  "error": 10,
  "gold_gap": 20
}
```