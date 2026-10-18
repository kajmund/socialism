# Document tags at ingest

Prepared document knowledge, not legal proof.
Classification is reused from frozen document-type B.
A is deterministic extraction. B is one Jev call per document.
User corrections survive re-ingest. No approval threshold.

| Variant | Precision | Recall | Hits | Extras | Misses | Jev/doc | Latency ms/doc |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 86.5% | 94.1% | 32 | 5 | 2 | 0.000 | 0.000 |
| B | 91.4% | 94.1% | 32 | 3 | 2 | 1.000 | 384.076 |

## Per class

### A

| Class | Precision | Recall | Gold |
|---|---:|---:|---:|
| employment_type | 77.8% | 100.0% | 7 |
| notice_period | 100.0% | 85.7% | 7 |
| confidentiality | 91.7% | 91.7% | 12 |
| non_compete | 66.7% | 100.0% | 2 |
| billing_model | 80.0% | 100.0% | 4 |
| work_location | 100.0% | 100.0% | 2 |

### B

| Class | Precision | Recall | Gold |
|---|---:|---:|---:|
| employment_type | 100.0% | 71.4% | 7 |
| notice_period | 100.0% | 100.0% | 7 |
| confidentiality | 92.3% | 100.0% | 12 |
| non_compete | 66.7% | 100.0% | 2 |
| billing_model | 80.0% | 100.0% | 4 |
| work_location | 100.0% | 100.0% | 2 |

## Cost and storage

Total Jev calls: 16.
Wall seconds: 6.351.
Store write seconds: 0.018.
OverGraph filter seconds: 0.002.
TextUnits unchanged: True.
Type correction survives reclassify: True.
Rejected tag stays rejected: True.
Tenant isolation: True.

A hits 32 / gold 34, B hits 32 / gold 34. Choose from the table. No quality threshold was set.

## Sources and confidence

| Variant | Validated hits | Passage ok | Unvalidated | Wrong passage |
|---|---:|---:|---:|---:|
| A | 32 | 29 | 0 | 3 |
| B | 22 | 20 | 10 | 2 |

B confidence: n=35, min=0.02, max=1.00, mean=0.871.
Confidence is Jev's raw value. It is not a calibrated
legal probability and was not used as a threshold.

A extras: Avtal_01 probationary, Avtal_03 permanent,
Avtal_08 secrecy, Avtal_13 non-compete, Avtal_59 hourly.
A misses: Avtal_11 notice 1 month, Avtal_36 secrecy.

B extras: Avtal_05 fixed price, Avtal_08 secrecy,
Avtal_13 non-compete.
B misses: Avtal_02 permanent, Avtal_04 fixed term.

## Recommendation

Keep A as the cheap ingest candidate. Keep B as an
experimental alternative for more semantic classes.
Jev improved precision, not recall, and lost sources.

The OverGraph data model is ready to reuse later:
stored classification, tags, user corrections, and
tenant-scoped filters. Automatic tags stay proposals,
not legal facts. See `document-tags-lifecycle-v1.md`.

Do not start Socialism production ingest from this
experiment. Tabular Review remains the path for
legal answers. Keep confidence diagnostic only.

## What this is not

- Not a change to Tabular `answer_cell`.
- Not Dense or Hybrid retrieval.
- Not a new coverage controller.
- Not production ingest.
- Not a calibrated legal confidence.
