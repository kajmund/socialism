# Tabular Review holdout run

Current ingest. Current embeddings. P0. One Jev `answer_cell`.
No structural preprocess. Default stays D.

| Variant | Strategy | k | Full success | Positive correct | Negative stayed | False on silent |
|---|---|---:|---:|---:|---:|---:|
| D | hybrid | 5 | 79% (79/100) | 63% (27/43) | 91% (52/57) | 5 |
| E | dense | 5 | 89% (89/100) | 91% (39/43) | 88% (50/57) | 6 |
| K | hybrid | 10 | 87% (87/100) | 81% (35/43) | 91% (52/57) | 4 |

300 Jev calls. Same P0. Same embeddings. Gold written before models.

## Reading

E recovered 12 more of the 43 addressed cells than D
(27 → 39) and added one silent false answer (5 → 6).
That is not a corresponding false-positive cost.
Full success 79% → 89%.

K is between them: +8 positive versus D, one fewer
silent false, still four positive cells behind E.
No reason to pay for ten hybrid candidates.

The four cells E still misses are nearby or
negative-form answers: a property-sale waiver
(`Avtal_24` cap), two explicit non-renewals
(`Avtal_40`, `Avtal_43`), and approved-system
storage as confidentiality (`Avtal_58`).

Default stays hybrid k=5 / D. E is now a strong
candidate, not an automatic switch. Structural
TextUnit preprocess stays a later experiment.

## What this is not

- Not a default change.
- Not a new ingest.
- Not Cerebras or Qwen.
