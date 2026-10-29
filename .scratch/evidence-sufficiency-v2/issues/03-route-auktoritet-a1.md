# Route-auktoritetens omfattning (A1)

Type: grilling
Status: resolved
Blocked by: –

## Question

Vilket routingkontrakt ska A1 införa, och vilka Jev-signaler får veto:a ett
`sufficient`?

Utgångspunkt: specen säger PASS + UNCERTAIN → insufficient. Live-spårningen
visar att **alla** gate-PASS-fall hade route `UNCERTAIN`, även
`short_sufficient` — där bara `follow_up_change` 0.11 > risk ceiling 0.10 avgör.
Strikt A1 skulle alltså göra den positiva kontrollen insufficient live.

Beslut som ticketen ska låsa:

- Vad är ett giltigt slutligt routingbeslut som får auktorisera `sufficient`?
  Ska `FINISH` bära ett explicit utfall (`sufficient` / inte sufficient), och
  vilka av de fem NOUL-signalerna får delta i det utfallet?
- Får `follow_up_change` / `additional_source` veto:a en PASS-grind, eller är de
  bara research-planeringssignaler? Om de inte får veto:a: vilken regel ersätter
  dem (t.ex. endast `answerable_now`, `material_gap`, `contradiction`)?
- Vad händer vid saknat, ofullständigt eller ogiltigt route-svar?
- Hur mappas intern status (`uncertain`) och publik draft (`sufficient |
  insufficient`) utan att uppgradera något?
- Ska `classify_research_decision` återanvändas oförändrad, wrappas, eller
  behöver den ett explicit utfalls-enum? Trösklarna får inte ändras i
  huvudjämförelsen.
- Acceptanstester: PASS + icke-sufficient route får aldrig ge `sufficient`; FAIL
  + Jev sufficient får aldrig ge `sufficient`; saknad route fail-closed; ett
  giltigt sufficient får fortfarande godkännas; `short_sufficient` ska förbli
  `sufficient` under den valda regeln — visa hur, givet de uppmätta
  live-svaren.

Leverans: ett skriftligt A1-kontrakt (regler, statusmappning, testmatris,
provenance) som kan implementeras utan fler beslut.

## Answer

**Beslut 2026-10-22 (grilling med användaren).** A1-kontraktet är låst.
Trösklarna är oförändrade; det är vilka signaler som får auktorisera
`sufficient` som ändras.

### Auktoritetspredikat (Q1)

`quality_gate` är nödvändig men inte tillräcklig. Ett `sufficient` kräver:

1. `quality.allows_sufficient == True` (inga gate-reasons, `semantic_complete`).
2. Ett giltigt route-svar med `final_outcome == "sufficient"`.

`final_outcome == "sufficient"` beräknas ur fyra signaler med dagens trösklar:

| Signal | Krav |
| --- | --- |
| `answerable_now` | `>= 0.9` (sufficient-tröskeln) |
| `material_gap` | `<= 0.1` (`1 - sufficient_tröskeln`) |
| `contradiction` | `<= 0.1` |
| `confidence` | `>= 0.8` (confidence-tröskeln) |

`confidence` är `min(noul_confidence(x))` över **alla fem** route-svaren — samma
beräkning som `ResearchFastDecision`/`classify_research_decision` använder i dag.
Den mäter tillförlitligheten i samtliga bedömningar, inte bara
`answerable_now`.

`follow_up_change` och `additional_source` auktoriserar inte `sufficient` och
veto:ar det inte heller; de styr fortsatt research. De deltar i
`confidence`-beräkningen men får aldrig åsidosätta ett ouppfyllt krav i den
deterministiska grinden.

### Explicit utfall (Q2)

`RouteDecision` får
`final_outcome: Literal["sufficient", "insufficient", "uncertain"] | None`.
`choice` behåller workflow-kommandona
`FINISH / RUN_SUBWORKFLOW / ESCALATE_NARRATIVE / UNCERTAIN`;
`map_jev_outcome` får bara välja kommando, aldrig implicera samtycke. `FINISH`
med `final_outcome is None` är ogiltigt (fail-closed). `jev_outcome` (rå
klassificering) behålls för spårbarhet.

### Statusmappning (Q3, Q4)

| Gate | Route | Intern status | Draft | Reason |
| --- | --- | --- | --- | --- |
| PASS | FINISH + sufficient | sufficient | sufficient | – |
| PASS | FINISH + insufficient | insufficient | insufficient | `route_insufficient` |
| PASS | FINISH + uncertain | uncertain | insufficient | `route_uncertain` |
| PASS | FINISH utan/ogiltigt utfall | failed | insufficient | `route_missing` / `route_invalid` |
| FAIL | valfri | oförändrat (escalate/subworkflow/insufficient/uncertain) | insufficient | gate-reasons |
| programmatic | ingen route | deterministiskt | deterministiskt | – |

Q5: `can_assess_programmatically`-vägen (`prepare → emit`) undantas; inget
route-krav. Deterministisk-first vinner.

### Vad A1 inte ska göra

A1 ska **inte** lösa `tail_counterevidence` eller `late_evidence`. De ligger kvar
som kända negativa kontroller tills A3 inför faktaparsbedömning. A1 isolerar
enbart auktoritetsfelet.

### Testmatris

1. PASS + FINISH + `final_outcome=uncertain` → status `uncertain`, draft
   `insufficient`, reason `route_uncertain`.
2. PASS + FINISH + `final_outcome=insufficient` → status `insufficient`, draft
   `insufficient`, reason `route_insufficient`.
3. PASS + FINISH + `final_outcome=sufficient` → `sufficient` (positiv kontroll).
4. FAIL + FINISH + `final_outcome=sufficient` → aldrig `sufficient`.
5. FINISH utan `final_outcome` eller med ogiltigt värde → `failed`.
6. `follow_up_change=0.11`, `additional_source=0.06`, övriga
   auktoritetssignaler pass → `sufficient` (låser Q1; matchar live
   `short_sufficient`).
7. Lågt `follow_up`/`additional` kan inte rädda ett FAIL till `sufficient`.
8. Programmatic-vägen: ingen route, deterministiskt utfall bevaras.
9. `FINISH` ensamt ger aldrig `sufficient` — `final_outcome` måste styra.

### Implementationsnoter (handoff)

- Ny `authoritative_outcome()` i `sufficiency_experiment/route.py`, som
  återanvänder `parse_noul`, `noul_confidence` och dagens trösklar
  (0.9 / 0.1 / 0.8). `classify_research_decision` och produktionen lämnas orörda.
- `decide_route` sätter `final_outcome` från `authoritative_outcome()` och
  kommandot från `map_jev_outcome`.
- `_emit_status` kräver `final_outcome == "sufficient"`; `_emit` mappar
  route-reasons. `narrative_unbound`-undantaget ligger kvar på
  eskaleringsvägen (gate FAIL), aldrig på sufficient-vägen.
- `trace.py` serialiserar `final_outcome`.
- Scripted Jev utökas (test double) med route-utfall `uncertain` och
  `insufficient` så testmatrisen kan köras utan nätverk.
- **Divergens att granska i slutgranskningen:** produktionens
  `would_short_circuit` kräver alla fem signaler; A1:s auktoritet fyra.
  Divergensen är avsiktlig (produktionen faller tillbaka på LLM vid
  `uncertain`; A1 mäter deterministisk auktoritet utan LLM) och får inte
  smyga in i produktionsvägen.
