# Mätprotokoll för armarna

Type: grilling
Status: resolved
Blocked by: 02, 05

## Question

Hur mäts A0, A1, A2, A3 och B så att en förbättring inte kan tillskrivas fel
ändring?

Beslut som ticketen ska låsa:

- Repetitioner: hur många live-körningar per arm, vilka fall kräver två
  oberoende repetitioner, och hur variationen redovisas.
- Kall/varm körning: vad som får cachas, vad som måste vara kallt, och hur
  cache-träffar redovisas separat.
- Metrics: accuracy, false-sufficient, false-insufficient, precision/recall för
  märkta motsägelsepar, unresolved conflicts, nedgraderade sufficient, oenighet
  route/gate, täckning per nivå.
- Prestanda: wall time, Jev-anrop, narrativa anrop, tokens där tjänsten
  rapporterar dem, tecken, kandidatpar/jämförda par, concurrency, p50/p95 per
  steg, timeouts/429/providerfel, kostnad per fråga och per korrekt beslut.
- Jämförelse: A0 fryst mot varje arm; PR #420-baslinjen är en publicerad
  mätning, inte en samtidig körning — hur det markeras.
- Artefaktformat och versionering, fält per arm, samt exakt hur acceptanskriterierna
  i specen §11 beräknas per arm.
- Scripted/live-separation: vad som får köras i CI och vad som kräver riktiga
  anrop.
- **Två täckningstyper:** execution coverage (alla valda jobb hanterade,
  deterministiskt mätbar) och semantic coverage (evidens för att relevanta
  motsägelser inte missats; kräver facit eller verifierbar strategi). Utan
  facit ska semantic coverage vara `not_measured`, aldrig `complete`.
- **Tre par-tillstånd:** ej valt par (kandidatgenereringen rankar bort det),
  budgetutelämnat par (valt som kandidat men fick inte plats) och obehandlat par
  (valt för Jev men kunde inte bedömas). De får inte automatiskt samma
  konsekvens: execution coverage täcker de två senare, medan semantic coverage
  kräver facit.
- **Budget:** höj inte `max_pairs_per_need=40` för att få gröna siffror. Bevisa
  först att kandidatgenereringen kan begränsa sökytan utan att tappa avgörande
  motsägelser; annars blir lösningen korrekt i teorin men för dyr i praktiken.
- **A0-baslinje:** använd den frysta A0-artefakten (två rep, `b55eae13`,
  `jev-1.14.0`) och redovisa intervall, inte en enskild siffra. A1-armen kräver
  ticket 13 innan A0/A1/A2/A3 kan jämföras rättvist.

Leverans: mätprotokoll + artefaktschema + acceptansformler, redo att användas i
fas 2–6.

## Answer

**Beslut 2026-10-23 (grilling med användaren).** Protokollet är låst i commit
`93002f99`, före någon armjämförelse.

### Artefakter

- `docs/architecture/evidence-sufficiency-measurement-protocol.md` — protokollet.
- `backend/tests/integration/baselines/measurement-protocol-v1.json` — maskinläsbar
  förregistrering (armar, körningar, kassett, mått, PASS/FAIL, artefaktnamn).
- `cassette.py` — experiment-only Jev-kassett: nyckel = questions-hash +
  kanoniskt state-hash + modell, strikt ordning, saknad post = fel.
- `arm_quality.py` — semantiska och operativa formler; `CaseOutcome`,
  `semantic_metrics`, `operational_metrics`, `cost_metrics`.
- `tests/test_sufficiency_experiment_measurement.py` — 7 tester för kassett och
  formler.

### Låsta beslut

| Fråga | Beslut |
| --- | --- |
| Q1 Semantisk kvalitet | Endast rena körningar; tekniska fel exkluderas och får aldrig räknas som detektion |
| Q2 Operativ kvalitet | Alla live-rep; raw accuracy, operational success, felkvot, `sufficient_on_failed_call`, stabilitet |
| Q3 Parad metod | Kassett-replay i strikt ordning + separata live-rep; saknad post = fel, nya anrop live och märkta |
| Q4 PASS/FAIL | Semantiska kontrakt per arm + operativ stabilitet; kostnad redovisas utan godtyckligt tak |
| Q5 A0 | Fryst artefakt orörd; ny parad A0-referens under protokollet |
| Q6 Armordning | A0/A2/A3 nu, A1 efter ticket 13, B efter A3-beslut |

### Semantisk vs operativ kvalitet

Semantisk: `clean = inte technical_failure och coverage_gate_complete`;
accuracy/false-sufficient/false-insufficient/confusion/TP/false contradictions
beräknas endast på rena körningar; exkluderade körningar räknas separat.

Operativ: alla rep; `operational_success = correct and clean`;
`technical_failure_rate`; `sufficient_on_failed_call` måste vara 0;
verdict-stabilitet över rep med `unstable_unexplained` separat.

Kostnad: Jev-anrop, indata-tecken, embedding/LLM-anrop, latens, Jev-latens,
`cost_per_detected_contradiction`, `cost_per_correct_decision`.

### PASS/FAIL (förregistrerade)

Semantiskt: A1 får inte göra PASS+route-uncertain till sufficient; A2 får inte
lösa forced 0.95-motsägelse vid duplicate 0.89; A3 får inte lämna tail/late/
independent som sufficient; `short_sufficient` kvar sufficient; inga falska
motsägelser på compatible; A3 clean false-sufficient ≤ A0 clean; parbudget 40
oförändrad.

Operativt: `sufficient_on_failed_call == 0`; felkvot och varje fel spårbart;
verdict-skillnader förklaras av registrerat fel; ingen dold fallback/retry.

### Budget

`max_pairs_per_need=40` höjs inte för gröna siffror. Innan en höjning måste
kandidatgenereringen visas behålla avgörande motsägelser med mindre sökning.

### Nästa steg

[A1-implementationen (ticket 13)](13-implementera-route-auktoritet-a1.md) krävs
innan A1 får ingå. Själva armkörningen läggs i ticket 14.
