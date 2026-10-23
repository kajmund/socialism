# B3b – Svårare facit och beslutskvalitet

Type: task
Status: resolved
Blocked by: 17

## Question

Kan B3:s prioritering bevisa mervärde när de kända motsägelseparen inte redan
ligger på rank 1?

- Lägg till verifierade lågrankade motsägelsepar, särskilt för `late_evidence`
  och `large_567k`, samt minst två nya negativa kontrollfall. Dokumentera facit
  per par utan att läcka in i prioriteringen.
- Kör A/B/C över dessa fall med Recall@Budget för k = 1, 5, 10, 20, 40.
- Kör därefter faktiska Jev-bedömningar på valda par vid minst två budgetar och
  mät decision_correctness, evidence_coverage, false-sufficient och
  false-insufficient separat.
- Förregistrera adoptionskriterium före körning: B3 får ersätta A3:s ordning
  endast vid samma/bättre recall med mindre budget eller bättre beslutskvalitet
  utan fler false-sufficient, och utan att 40-parsbudgeten höjs.
- Om B3-B/C inte slår A: behåll nuvarande ordning och stäng B3.

## Låst protokoll före körning (2026-10-23)

**Separera tre mätningar per fall:**

1. **Candidate Recall** – finns det relevanta paret bland *alla* genererade
   kandidater innan budget/ranking?
2. **Recall@Budget** – hamnar det inom k = 1, 5, 10, 20, 40 för varje
   prioriteringsarm (A nuvarande, B metadata, C embeddings-proxy)?
3. **Decision Correctness** – bedömer Jev det kända paret korrekt
   (motsägelse vs inte motsägelse), oberoende av om det valdes?

**Fryst facit ska innehålla fyra kategorier:**

- Tydliga motsägelser som nuvarande ordning hittar (duplicate, independent,
  tail_claim).
- Subtila motsägelser långt ned i kandidatlistan (late_evidence, large_567k).
- Semantiskt liknande men förenliga par (compatible_periods/entities).
- Motsägelser som kandidatgenereringen helt missar (syntetiskt synonymfall utan
  delade tokens).

**Felattribuering per fall:** `candidate_miss`, `ranking_beyond_budget`,
`jev_wrong_verdict`, `none`. Slutsatsen ska peka ut vilken av dessa som
dominerar late/large.

**Krav:** fler upptäckta motsägelser räknas inte som framgång om
false-sufficient, coverage eller slutlig beslutskvalitet försämras. SSR/embeddings
är kompletterande signaler; generell similarity får inte dominera. Slutlig
coverage mäts separat från Recall@Budget.

## Answer

**Körd 2026-10-23** (commit `7b4320c8`) enligt det låsta protokollet: candidate
recall, Recall@Budget och Jev-beslut mäts separat.

| Fall | Kategori | Candidate recall | Rank A/B/C | Jev på facit | Attribuering |
| --- | --- | --- | --- | --- | --- |
| duplicate_contradiction | clear | ja | 1/1/1 | SCOPE_DIFFERENCE (fel) | jev_wrong_verdict |
| independent_contradiction | clear | ja | 1/1/1 | CONTRADICTS | none |
| tail_claim_contradiction | clear | ja | 1/1/30 | CONTRADICTS | none |
| late_evidence | subtle | ja | **1129/1/1134** | CONTRADICTS | ranking_beyond_budget |
| large_567k | subtle | inget fryst facitpar | — | ej utvärderat | facit_unavailable |
| compatible_periods | compatible | ja | 1/1/1 | SCOPE_DIFFERENCE (korrekt) | none |
| compatible_entities | compatible | ja | 1/1/1 | SCOPE_DIFFERENCE (korrekt) | none |
| candidate_miss_synonyms | candidate miss | **nej** | — | SCOPE_DIFFERENCE (fel) | candidate_miss |

Recall@Budget över de fem motsägelsefall som har facit:

| Arm | @1 | @5 | @10 | @20 | @40 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A nuvarande | 0.60 | 0.60 | 0.60 | 0.60 | 0.60 |
| B metadata | **0.80** | **0.80** | **0.80** | **0.80** | **0.80** |
| C embeddings-proxy | 0.40 | 0.40 | 0.40 | 0.40 | 0.60 |

Jev decision accuracy på utvärderade facitpar: 0.714 (5/7).

### Slutsats

- `late_evidence` är ett **rankningsfel**: paret genereras men ligger på rank
  1129; metadata-prioritering lyfter det till rank 1 och ger +0.20 recall vid
  varje budget.
- `candidate_miss_synonyms` är ett **kandidatgenereringsfel**, och Jev bedömer
  även paret fel — båda stegen är öppna.
- `large_567k` saknar fryst facitpar; felet kan inte attribueras.
- `duplicate_contradiction` har rank 1 men Jev svarade SCOPE_DIFFERENCE på
  direkt facit-bedömning; beslutskorrektheten behöver live-repetition.
- Embeddings dominerar inte: proxy är sämre än metadata och trycker ner
  `tail_claim_contradiction` till rank 30.

**Ingen ordning antas ännu.** Nästa steg är B3c: fullt live-arm med
metadata-ordningen, två repetitioner, och slutlig beslutskvalitet/coverage/
false-sufficient mätt separat.
