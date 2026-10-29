# B-instrumentering: narrativ precheck

Type: grilling
Status: resolved
Blocked by: 03, 08, 09, 10, 13, 14

## Question

Hur ska variant B instrumenteras så att den mäter narrativets bidrag utan att
blanda in nya mekanismer?

Utgångspunkt: den förregistrerade designen i
`docs/architecture/evidence-sufficiency-narrative-precheck.md` (trigger ≥20 000
tecken eller ≥3 oberoende källor, endast vid would-be-sufficient, ett anrop,
downgrade-only, fail-closed). Beslut som ticketen ska låsa:

- Promptkälla: experimentets hårdkodade `NARRATIVE_SYSTEM_PROMPT` vs en riktig
  prompt-field. Projektregeln säger prompts i DB; vad gäller för experimentet,
  och vad blockerar produktionskoppling? Ingen hårdkodad prompt får smyga in i
  produktionsvägen.
- Modellkonfiguration och live-binding i en offline-benchmark utan DB/session.
  Vilken klient/completer återanvänds, och hur rapporteras `unavailable` utan
  att scriptade svar ersätter?
- Payload: aggregationer + faktapar/konflikter från A3 + deterministiskt urval
  av passager + explicit omitted-lista. Vad är obligatoriskt, och vad får
  utelämnas?
- Verktyg: en-anropsarmen ska ha noll verktyg. Om verktygsanrop införs är det en
  separat konfiguration — beslut om den ska skapas nu eller skjutas upp.
- Trigger, budget och nedgradering enligt designen; hur B:s utfall kopplas till
  A1-status utan att uppgradera något.
- Acceptans: båda fällorna får inte ge sufficient; `short_sufficient` förblir
  sufficient med noll narrativa anrop; högst ett anrop; fail-closed vid
  timeout/fel/otillräcklig provenance; vad som räknas som "mätbar kvalitetsvinst"
  i förhållande till latens/kostnad.

Leverans: B-kontrakt + live-bindningsplan + acceptans, redo att implementeras
efter A1–A3.

## Answer

**Beslut 2026-10-23 (grilling med användaren).** B är ett mätbart verktyg, inte
en fri domare. Implementerat som B0 i commit `360400c2`; A3 är oförändrad
jämförelsearm och B har ingen beslutsrätt.

### Låsta principer

- **Ingen beslutsrätt:** `gap_review` registreras på rapporten och läses aldrig
  av route, gate eller emit. A3:s dom står kvar oförändrad.
- **Begränsade workflows:** den narrativa modellen får bara föreslå workflows ur
  `ALLOWED_WORKFLOWS`; okända förslag avvisas (`invalid_workflow`).
- **Ingen förklaring av saknad evidens:** B får rapportera öppna frågor,
  saknad evidens och nästa workflow — inte ändra täckningsbedömningen.
- **Två separata mått:** `contradiction_detection`, `evidence_coverage` och
  `decision_correctness` hålls åtskilda i B-artefakten. Ett negativt
  täckningsbeslut är inte bevis på att Jev missförstått materialet.
- **Prompt:** experiment-only (`narrative_gap.py`), flaggad; ingen
  produktionsprompt eller assessor påverkas.

### B0-resultat (en live-körning, `gpt-oss-120b`)

| Mått | Resultat |
| --- | --- |
| Gap true positives | 1 / 1 (`late_evidence`) |
| Gap false negatives | 0 |
| Gap false positives | 9 / 9 |
| Flaggar alla fall | 10 / 10 |
| LLM-anrop / inmatning | 10 / ~33 300 tecken |
| Gap-latens | ~7,2 s totalt (~0,7 s per fall) |
| Ogiltiga workflowförslag | 0 |

Slutsats: prechecken hittar det förväntade gapet men flaggar allt, inklusive
`short_sufficient`. Med nuvarande breda schema är precisionen oanvändbar. Det
är ett B0-instrumenteringsresultat, inte bevis för eller emot Variant B. B1
måste skärpa både gap-facit och rapportkontraktet innan någon jämförelse med A3
görs.

### Nästa experiment (låst ordning)

| Experiment | Syfte | Beslutskriterium |
| --- | --- | --- |
| B0 – instrumentering | Mäta vad prechecken identifierar | Klart: hittar gapet men överflaggar |
| B1 – shadow | Köra utan beslutsmakt mot skärpt gap-facit | Tillför den något utöver A3? |
| B2 – workflow-styrd komplettering | SWE undersöker identifierade luckor | Förbättras false-insufficient utan nya false-sufficient? |
| B3 – adaptiv parbudget | Prioritera mest informativa faktapar | Samma/bättre kvalitet med färre Jev-anrop? |

Tio fall och en körning är diagnostik, inte generell precision. Samma låsta
fall behålls för jämförbarhet; därefter krävs nya, tidigare osedda fall.

### Artefakter

`tests/integration/baselines/b0-gap-review-v1.json`, `narrative_gap.py`,
`scripts/measure_b0_gap_review.py`, tester i
`tests/test_sufficiency_experiment_gap_review.py`.
