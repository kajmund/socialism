# 41 – Mänskligt verifierat klausullokaliseringsfacit

Type: task
Status: open
Blocked by: –

## Question

Ta fram ett litet men mänskligt verifierat facit för klausullokalisering på den
riktiga korpusen, innan ticket 40 mäter recall/precision.

- Minst kategorierna `termination_notice`, `price`, `automatic_renewal` och
  `liability_limitation`.
- Per avtal: närvaro/frånvaro, ordagrann klausul, dokumentversion, locator
  (stycke/tecken/punkt) och granskare/tid; frånvaro är ett riktigt negativ.
- Håll ut testavtal från ankarbiblioteket; granska inte med samma Jev/modell som
  systemet som testas.
- Versionera facit; synthetic_sme-generatormetadata får inte kallas
  mänskligt verifierat.

Leverans: versionerat facit + validering att locatorer löser till ordagrann text.

## Påbörjat 2026-10-24

- `backend/scripts/build_clause_review_candidates.py` bygger
  granskningskandidater från 35 syntetiska avtal × 4 kategorier (140 kort) med
  dokumentversion, styckeindex, ordagrann kandidattext, generatorhint och
  anchor/test-split.
- Artefakt: `synthetic_sme/ground_truth/clause_review_candidates_v1.json`.
- **Inget är facit:** `not_facit: true`, `review_status: pending_human_review`.
  Generatormetadata används endast för att välja granskningsfall.
- Nästa: ingesta dessa avtal (ticket 42) och kör korten genom admin
  Ja/Nej/Osäker; Ja ger verifierad klausul + locator, Nej får inte automatiskt
  bli “saknas” utan ska verifieras mot hela dokumentet.

## Status 2026-10-24

140 kandidatkort är genererade och finns i PR #430. De är uttryckligen inte
facit. Nästa steg är att köra dem genom admin Ja/Nej/Osäker efter ingest, med
separat anchor-/test-split och `verified_absent` först efter dokumentgranskning.
