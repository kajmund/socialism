# Jev presentation fix v1

Same 50 cases, stage-1 verdicts, and local dense top-5 as the A/B/C run. Only the Jev presentation changes: top-5 clauses are shown as primary evidence (`evidence_clauses`), not just excerpt choices.

| Arm | JevRecovery@5 (all NV) | NV-pos recovered | New FP errors | New SUPPORTED gold-gap |
|---|---:|---:|---:|---:|
| A | 5/14 | 3/3 | 0 | 2 |
| B | 6/14 | 3/3 | 1 | 2 |
| C | 6/14 | 3/3 | 1 | 2 |

## Groups

```json
{
  "positive": 20,
  "error": 10,
  "gold_gap": 20
}
```