# Structure-aware TextUnit embeddings

Search representation is not evidence.
Headings come from stored Structure paths.
Previous sibling uses the same structure_id.
No Jev. No legal parser. P0 and default D stay.

## First run

| Variant | Search text | Run now |
|---|---|---|
| A | Original TextUnit | Yes |
| B | Heading path + TextUnit | Yes |
| C | Heading path + previous sibling + TextUnit | Later |

Development documents: 40.
Spanned cells: 84.
Reserved holdout: 20 unused documents.

Do not tune B to the four known Dense misses.
Hypothesis 2 (Jev at ingest) is not built.

## Reserved documents

- Avtal_16_Praktikavtal.docx
- Avtal_26_Stiftelseurkund.docx
- Avtal_29_Samarbetsavtal.docx
- Avtal_37_Allmanna_villkor_B2B.docx
- Avtal_41_Borgensforbindelse.docx
- Avtal_44_Avbetalningsplan.docx
- Avtal_49_IT_drift_hostingavtal.docx
- Avtal_53_Overlatelse_immateriella_rattigheter.docx
- Avtal_56_Bidragsavtal_CLA.docx
- Avtal_59_Agilt_IT_konsultavtal.docx
- Avtal_62_PUB_GDPR_databehandlingsavtal.docx
- Avtal_65_Sponsringsavtal.docx
- Avtal_68_Hyresavtal_fordon.docx
- Avtal_72_Utbildningsavtal.docx
- Avtal_75_Visselblasarfunktion.docx
- Avtal_79_Hyresavtal_lokal_Goteborg.docx
- Avtal_82_Uppdragsavtal_styrelseledamot.docx
- Avtal_85_Konvertibelt_laneavtal.docx
- Avtal_88_Teckningsavtal_nyemission.docx
- Avtal_91_Inkramsoverlatelse.docx
