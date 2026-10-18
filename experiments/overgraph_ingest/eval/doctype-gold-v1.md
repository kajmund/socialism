# Document-type gold

Gold before models. Principal function, not clauses.
No Jev. No retrieval change. No `answer_cell` change.

## Counts

| Type | Documents |
|---|---:|
| Anställningsavtal (`employment_agreement`) | 5 |
| Konsultavtal (`consulting_agreement`) | 9 |
| Sekretessavtal (`nda`) | 2 |
| Personuppgiftsbiträdesavtal (`dpa`) | 2 |
| Leveransavtal (`supply_agreement`) | 10 |
| Hyresavtal (`lease_agreement`) | 9 |
| Överenskommelse om anställningens upphörande (`employment_termination_agreement`) | 2 |
| Annat (`other`) | 61 |

## Hard cases

| Case | Left | Right |
|---|---|---|
| employment_vs_termination_notice | Avtal_01_Tillsvidareanstallningsavtal.docx (employment_agreement) | Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx (employment_termination_agreement) |
| consulting_vs_supply | Avtal_05_Konsultavtal.docx (consulting_agreement) | Avtal_31_Leveransavtal.docx (supply_agreement) |
| nda_vs_secrecy_clause | Avtal_06_Sekretessavtal_ensidigt_NDA.docx (nda) | Avtal_05_Konsultavtal.docx (consulting_agreement) |
| dpa_vs_main_with_privacy | Avtal_62_PUB_GDPR_databehandlingsavtal.docx (dpa) | Avtal_46_SaaS_avtal.docx (supply_agreement) |
| employment_vs_termination_settlement | Avtal_01_Tillsvidareanstallningsavtal.docx (employment_agreement) | Avtal_13_Avgangsvederlagsavtal.docx (employment_termination_agreement) |
| termination_vs_dispute_settlement | Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx (employment_termination_agreement) | Avtal_92_Forlikningsavtal.docx (other) |

## What this is not

- Not clause classification.
- Not a new document analysis engine.
- Not a production ingest change.
