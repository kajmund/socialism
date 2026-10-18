# Document classification at ingest

One type per document. Principal function, not clauses.
A uses title, opening, headings, and stored metadata.
B is one Jev choice on the same view. C adds a fixed extra-text budget.
Type is stored on Document. TextUnits stay unchanged.

| Variant | Accuracy | Jev calls/doc | Latency ms/doc |
|---|---:|---:|---:|
| A | 81/100 (81.0%) | 0.000 | 0.000 |
| B | 86/100 (86.0%) | 1.000 | 271.778 |
| C | 84/100 (84.0%) | 1.000 | 277.201 |

## Precision and recall

### A

| Type | Precision | Recall | Gold |
|---|---:|---:|---:|
| Anställningsavtal | 62.5% | 100.0% | 5 |
| Konsultavtal | 100.0% | 55.6% | 9 |
| Sekretessavtal | 100.0% | 100.0% | 2 |
| Personuppgiftsbiträdesavtal | 100.0% | 100.0% | 2 |
| Leveransavtal | 66.7% | 100.0% | 10 |
| Hyresavtal | 81.8% | 100.0% | 9 |
| Överenskommelse om anställningens upphörande | 28.6% | 100.0% | 2 |
| Annat | 92.0% | 75.4% | 61 |

### B

| Type | Precision | Recall | Gold |
|---|---:|---:|---:|
| Anställningsavtal | 83.3% | 100.0% | 5 |
| Konsultavtal | 77.8% | 77.8% | 9 |
| Sekretessavtal | 100.0% | 100.0% | 2 |
| Personuppgiftsbiträdesavtal | 100.0% | 100.0% | 2 |
| Leveransavtal | 50.0% | 100.0% | 10 |
| Hyresavtal | 90.0% | 100.0% | 9 |
| Överenskommelse om anställningens upphörande | 100.0% | 100.0% | 2 |
| Annat | 100.0% | 80.3% | 61 |

### C

| Type | Precision | Recall | Gold |
|---|---:|---:|---:|
| Anställningsavtal | 83.3% | 100.0% | 5 |
| Konsultavtal | 75.0% | 66.7% | 9 |
| Sekretessavtal | 100.0% | 100.0% | 2 |
| Personuppgiftsbiträdesavtal | 100.0% | 100.0% | 2 |
| Leveransavtal | 45.5% | 100.0% | 10 |
| Hyresavtal | 90.0% | 100.0% | 9 |
| Överenskommelse om anställningens upphörande | 100.0% | 100.0% | 2 |
| Annat | 100.0% | 78.7% | 61 |

## Cost

Total Jev calls: 200.
Wall seconds: 55.212.
Store write seconds: 0.011.
OverGraph filter seconds: 0.003.
TextUnits unchanged: True.

A 81.0%, B 86.0%, C 84.0%. Jev beat the structure-only variant. Choose the method from this table. No quality threshold was set.

B changed 25 documents versus A: 14 fixed, 9 regressed.
C changed 2 versus B and both were regressions.

## Error classes

Hard cases that stayed distinct:

- Employment vs termination notice (01 vs 12): all variants correct.
- Consulting vs goods supply (05 vs 31): all variants correct.
- Stand-alone NDA vs a consulting agreement with secrecy (06 vs 05): all variants correct.
- DPA vs a SaaS main contract (62 vs 46): all variants correct.
- Employment vs severance that ends employment (01 vs 13): all variants correct.
- Termination instrument vs later dispute settlement (12 vs 92): A called 92 a termination. B and C did not.

A errors are mostly keyword collisions: openings that mention anställning, hyresavtal, ramavtal, or SaaS on documents whose principal function is something else. A also misses consulting documents whose title is not "konsultavtal" (36, 57, 66, 75).

B's remaining 14 errors are concentrated on one boundary: it over-calls `supply_agreement` for adjacent commercial documents (reseller, license, coworking, event, B2C terms, art commission, photo assignment, subcontract). Two professional assignments (audit letter, board member) were called consulting.

C did not fix any B error. Extra text moved the advertising agency and the offer terms into supply.

## What this is not

- Not a change to Tabular `answer_cell`.
- Not Dense or Hybrid retrieval.
- Not a new coverage controller.
- Not production ingest.
