# Jev property verification v1

Jev is a non-hard verifier of deterministic document properties. UNDECIDED is never treated as UNSUPPORTED.

## Verdict

```json
{
  "verdict": "jev_adds_precision_without_recall_loss",
  "conservative": true,
  "note": "Prefer keeping false positives over losing correct contracts. UNDECIDED is never treated as UNSUPPORTED."
}
```

## Metrics

| Group | SUPPORTED | UNSUPPORTED | UNDECIDED |
|---|---:|---:|---:|
| positive | 20 | 0 | 0 |
| error | 1 | 9 | 0 |
| gold_gap | 17 | 3 | 0 |

keep_rate_strict: 1.0000
keep_rate_cautious: 1.0000
false_rejection_count: 0
reject_rate_errors: 0.9000
error_miss_rate: 0.1000
gold_gap_agreement: 0.8500

## Lost documents under a simulated soft filter (positive controls)

```json
{}
```

## Latency and tokens

```json
{
  "latency_ms": {
    "total": 14107.707540941192,
    "mean": 282.15415081882384,
    "max": 1239.1923330142163
  },
  "tokens": {
    "prompt": 57075,
    "completion": 16112
  }
}
```

## Errors

```json
[]
```