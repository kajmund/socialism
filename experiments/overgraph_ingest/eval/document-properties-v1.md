# Document properties v1 (Track A, deterministic structure)

Model-free. Deterministic structure + a frozen relation taxonomy. Production is unchanged.

| Gold | Split | Pos | Extracted | PropertyRecall | PropertyPrecision | LookupCompleteness | RecoveredMissed | Missing | FP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| auto-renewal | seen | 20 | 19 | 0.9500 | 1.0000 | 0.9500 | 0 | 1 | 0 |
| notice-period | seen | 13 | 47 | 1.0000 | 0.2766 | 1.0000 | 2 | 0 | 34 |
| liability-cap | seen | 28 | 24 | 0.8214 | 0.9583 | 0.8214 | 2 | 5 | 1 |
| confidentiality | seen | 13 | 45 | 1.0000 | 0.2889 | 1.0000 | 7 | 0 | 32 |
| liability-secrecy-carveout | seen | 7 | 7 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 | 0 |
| governing-law | held_out | 75 | 79 | 1.0000 | 0.9494 | 1.0000 | 63 | 0 | 4 |
| force-majeure | held_out | 5 | 7 | 1.0000 | 0.7143 | 1.0000 | 0 | 0 | 2 |
| personal-data | decision_held_out | 15 | 35 | 1.0000 | 0.4286 | 1.0000 | 6 | 0 | 20 |
| assignment | decision_held_out | 8 | 26 | 1.0000 | 0.3077 | 1.0000 | 1 | 0 | 18 |

## Macro

```json
{
  "property_recall": 0.9746031746031746,
  "property_precision": 0.6581927228955687,
  "recovered_missed_total": 81,
  "missing_total": 6,
  "false_positive_total": 111,
  "lookup_completeness": 0.9746031746031746,
  "ranked_recall_20": 0.6853683353683354,
  "ranked_recall_50": 0.9346031746031745
}
```

## Verification (GROUNDED vs gold_supported)

| Gold | Extracted | GROUNDED | gold_supported | grounded-only |
|---|---:|---:|---:|---:|
| auto-renewal | 19 | 19 | 19 | 0 |
| notice-period | 47 | 47 | 13 | 34 |
| liability-cap | 24 | 24 | 23 | 1 |
| confidentiality | 45 | 45 | 13 | 32 |
| liability-secrecy-carveout | 7 | 7 | 7 | 0 |
| governing-law | 79 | 79 | 75 | 4 |
| force-majeure | 7 | 7 | 5 | 2 |
| personal-data | 35 | 35 | 15 | 20 |
| assignment | 26 | 26 | 8 | 18 |

## Limitations

- Capability test for nine pre-registered properties, not a generalization test.
- SUPPORTED here is rule-level plus a gold-anchored check; it is not an independent legal verification.
- Property lookup is not truncated to top-k and can be paginated through all matches.
