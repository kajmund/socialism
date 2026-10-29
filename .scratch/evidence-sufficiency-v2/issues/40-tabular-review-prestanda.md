# 40 – Tabular Review prestanda på riktiga 200 avtal

Type: task
Status: open
Blocked by: 42

## Question

Mät Tabular Review med det verifierade Overgraph-klausulbiblioteket på de
faktiska ~200 avtalen innan SSR jämförs mot D.

- Tid per review (fyllning, antal TextUnits, kolumner), cache hit rate och
  embeddingberäkning; inga Jev/LLM-anrop.
- Precision/abstention på ett litet mänskligt granskat urval; låg score ska
  förbli `Ingen träff`, aldrig “klausul saknas”.
- Kontrollera låsta celler och historik över omkörning samt återkallat ankare.
- Ingen produktionsändring; mätningen ska vara reproducerbar med artefakt.

Därefter ticket 38: SSR vs D för evidensurvalet.

## Utredning 2026-10-23: förutsättningarna saknas

- Det finns 424 syntetiska avtalsfiler i `synthetic_sme/contracts` och
  generatormetadata i `truth_model.json` (bl.a. `notice_months`,
  `auto_renew_months`, `liability_cap`, `pricing_model`).
- Det finns **inget mänskligt verifierat facit för klausullokalisering** med
  dokumentpositioner, och synthetic_sme är inte den riktiga kundkorpusen.
- Den befintliga 200-avtalsbenchmarken är scriptad; dess recall/svarstider får
  inte användas som produktmått.
- Därför kan ticket 40 ännu inte mäta precision/recall eller verklig UI-tid.
  Protokoll och facitschema ligger i
  `docs/architecture/tabular-review-benchmark-v1.md`.

Nästa: ticket 41 (mänskligt verifierat klausulfacit) och ticket 42 (riktig
ingest + mätharness). Därefter kan ticket 40 köras.

## Uppdelning 2026-10-24

- **Ticket 40 mäter teknik/prestanda** på den ingästa korpusen: tid till första
  rad, komplett tabell, backend-/UI-tid, cache hit rate, låsta celler och
  återkallelse. Det kräver ingen mänsklig facit, bara ticket 42.
- **Ticket 43 mäter kvalitet** (Recall@1/3/5, abstention, precision) mot det
  mänskligt verifierade facit från ticket 41.
