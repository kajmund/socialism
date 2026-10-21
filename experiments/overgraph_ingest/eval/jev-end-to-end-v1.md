# Jev end-to-end verification v1

Deterministic discovery -> Jev -> document-local dense -> Jev. Local dense runs only when Jev does not SUPPORT the first citation. A second UNSUPPORTED means NOT_VERIFIED, not absent.

## Groups

```json
{
  "positive": 20,
  "error": 10,
  "gold_gap": 20
}
```

## Stage counts

| Group | verified_at_discovery | verified_after_local_dense | not_verified |
|---|---:|---:|---:|
| positive | 17 | 0 | 3 |
| error | 2 | 0 | 8 |
| gold_gap | 17 | 0 | 3 |

recovery_count (UNSUPPORTED -> SUPPORTED after local dense): 0
recovery_rate_of_non_supported: 0.0000
local_dense_runs: 14
local_dense_skip_rate: 0.7200

## Jev calls and latency

```json
{
  "jev_calls": {
    "total": 64,
    "mean": 1.28
  },
  "latency_ms": {
    "mean": 352.0432625198737,
    "p50": 284.35362501477357,
    "p95": 562.7807563840179,
    "max": 810.547334025614
  }
}
```

## Errors

```json
[]
```