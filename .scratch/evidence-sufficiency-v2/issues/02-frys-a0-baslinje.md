# Frys A0-baslinje och golden cases

Type: task
Status: resolved
Blocked by: –

## Question

Vilken exakt A0-baslinje ska alla armar jämföras mot, och är den reproducerbar?

Arbetet (inte en designfråga):

1. Frys commit-hashar, konfigurationer, modell-id:n och de befintliga
   artefakterna `sufficiency-experiment-live-v1.json` och
   `sufficiency-contradiction-trace-v1.json`.
2. Kör **två oberoende live-repetitioner** av de fyra benchmarkfallen
   (`tail_counterevidence`, `late_evidence`, `large_567k`,
   `short_sufficient`) via den befintliga trace-vägen.
3. Spara varje körning som artefakt med run-metadata (datum, commit,
   `jev_model`, trösklar, anropsantal, latens) under
   `backend/tests/integration/baselines/` eller en dokumenterad
   experimentskatalog.
4. Verifiera att domarna reproduceras och redovisa variationen i
   kontradiktions-, stöd- och relevansscores mellan körningarna.
5. Bekräfta att PR #426 och produktionskoden är orörda.

Leverans: artefakt-sökvägar + hash, en kort variationstabell och en bekräftelse
på att A0 är reproducerbar. Detta är fakta som mätprotokollet vilar på.

## Answer

**Körd 2026-10-23.** A0 fryst från den ursprungliga PR #422/#426-vägen vid
commit `b55eae13`; inga bedömningsregler ändrades under frysningen.

### Artefakter

- `backend/tests/integration/baselines/sufficiency-a0-freeze-v1.json` —
  metadata, commit, config, per-rep-sammanfattning, SHA256 för råfilerna och
  variansanalys.
- `...-rep1-raw.json` och `...-rep2-raw.json` — råresultat inklusive varje
  Jev-anrops svar, modell, latens och input-tecken.
- `backend/scripts/freeze_a0_baseline.py` — drivrutinen som kördes två gånger.

### Förutsättningar

- Commit: `b55eae13` (PR #426-head, oförändrade regler).
- Modell: `jev-latest` begärd, `jev-1.14.0` resolved i båda repen.
- 1 043 Jev-försök per rep, 0 LLM-anrop; golden cases oförändrade (fyra
  A0-fall).

### Resultat

| Rep | Accuracy | False-sufficient | Late evidence | Klientfel |
| --- | ---: | ---: | --- | ---: |
| 1 | 0.75 | 0.33 | insufficient (ett felat anrop) | 2 |
| 2 | 0.50 | 0.67 | sufficient | 2 |

Båda repen hade 2 transienta `JevClientError` av 1 043 anrop. I rep 1 landade
ett fel i `late_evidence`, blev `evaluation_errors` och blockerade
`sufficient`; i rep 2 landade båda i `large_567k`, som redan var insufficient.
A0 är därför ett intervall, inte en punkt — armjämförelser ska använda båda
repen.

### Implikation

A1-armen kan inte mätas förrän route-auktoritetskontraktet är implementerat;
det ligger nu i ticket 13. Mätprotokollet (ticket 10) använder den frysta
A0-baslinjen och de två repen.
