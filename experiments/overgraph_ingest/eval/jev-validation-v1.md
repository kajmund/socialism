# Jev chain broad validation v1

Pipeline: deterministic discovery -> Jev -> document-local dense (gold.query) -> Jev, with the presentation fix. All 111 suspected false positives plus a balanced >=100 gold-positive sample. Preliminary AI labels are agreement only, never definitive gold.

## Totals

| Group | SUPPORTED | UNSUPPORTED | UNDECIDED |
|---|---:|---:|---:|
| positive | 116 | 0 | 0 |
| suspected_fp | 85 | 26 | 0 |

recall_loss_total: 0 (rate 0.0000)
uncertain_share positive: 0.0000
uncertain_share suspected_fp: 0.0000

## Local dense

```json
{
  "runs": 77,
  "recovered": 51,
  "skip_rate": 0.6607929515418502
}
```

## Latency and Jev calls

```json
{
  "latency_ms": {
    "mean": 342.39543026794234,
    "p50": 258.15879201400094,
    "p95": 560.1567123987478,
    "max": 856.957957992563
  },
  "jev_calls": {
    "total": 304,
    "mean": 1.3392070484581498
  }
}
```

## Preliminary agreement (30 labeled FP)

```json
{
  "gold_gap": {
    "supported": 19,
    "not_supported": 1
  },
  "wrong_property": {
    "supported": 0,
    "not_supported": 5
  },
  "wrong_relation_or_polarity": {
    "supported": 2,
    "not_supported": 3
  }
}
```

## Per property

```json
{
  "assignment_restriction": {
    "positive": {
      "SUPPORTED": 8,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 6,
      "UNSUPPORTED": 12,
      "UNDECIDED": 0
    }
  },
  "automatic_renewal": {
    "positive": {
      "SUPPORTED": 19,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 0,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    }
  },
  "confidentiality_obligation": {
    "positive": {
      "SUPPORTED": 13,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 29,
      "UNSUPPORTED": 3,
      "UNDECIDED": 0
    }
  },
  "force_majeure": {
    "positive": {
      "SUPPORTED": 5,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 0,
      "UNSUPPORTED": 2,
      "UNDECIDED": 0
    }
  },
  "governing_law": {
    "positive": {
      "SUPPORTED": 20,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 3,
      "UNSUPPORTED": 1,
      "UNDECIDED": 0
    }
  },
  "liability_limitation": {
    "positive": {
      "SUPPORTED": 16,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 0,
      "UNSUPPORTED": 1,
      "UNDECIDED": 0
    }
  },
  "liability_secrecy_carveout": {
    "positive": {
      "SUPPORTED": 7,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 0,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    }
  },
  "personal_data_processing": {
    "positive": {
      "SUPPORTED": 15,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 16,
      "UNSUPPORTED": 4,
      "UNDECIDED": 0
    }
  },
  "termination_notice": {
    "positive": {
      "SUPPORTED": 13,
      "UNSUPPORTED": 0,
      "UNDECIDED": 0
    },
    "suspected_fp": {
      "SUPPORTED": 31,
      "UNSUPPORTED": 3,
      "UNDECIDED": 0
    }
  }
}
```