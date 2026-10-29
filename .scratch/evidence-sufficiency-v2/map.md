# Karta: Evidence Sufficiency v2 (A1–A3 + B)

Lokal markdown-tracker. Karta och tickets ligger under
`.scratch/evidence-sufficiency-v2/`.

## Destination

En **beslutscomplete plan** för Evidence Sufficiency v2: A1 (route-auktoritet),
A2 (säker konflikthantering), A3 (faktaparsbedömning) och B (narrativ precheck)
har var och en ett låst kontrakt, en reuse-vs-new-matris, frysta golden cases,
täcknings- och mätprotokoll samt acceptanskriterier nog att implementera utan
fler designbeslut.

Ingen kod skrivs, ingen produktionsändring görs och inget mergas i denna effort.
Implementation och live-körningar för fas 1–6 lämnas över efter att kartan
stängts.

## Notes

- Domän: research → SWE-workflows, Jev-beslut, assessment. Läs vid behov
  `docs/architecture/workflow-first-execution.md`,
  `docs/architecture/reuse-before-new.md`,
  `docs/guides/evidence-sufficiency-experiment.md`,
  `docs/guides/evidence-sufficiency-contradiction-trace.md` och
  `docs/architecture/evidence-sufficiency-narrative-precheck.md`.
- Skills: `grilling` + `domain-modeling` för beslutstickets; `research` för
  inventeringen. `reuse-before-new` är obligatorisk för varje arm.
- Fryst utgångspunkt: `main` (PR #422), PR #426 (öppen, orörd),
  `b5bb4b71` (trace-verktyg + artefakter). Baslinjeartefakter:
  `backend/tests/integration/baselines/sufficiency-experiment-live-v1.json`
  och `sufficiency-contradiction-trace-v1.json`.
- Alla armar är opt-in i
  `backend/app/services/research/sufficiency_experiment/`; ingen import i
  produktionsassessorn.
- Mätning: scriptade och live-resultat redovisas separat. Live-acceptans kräver
  faktiska modellanrop; scriptade svar är plumbing, inte modellkvalitet.
- Varje ticket refereras med sitt namn, inte sin siffra, i narration och beslut.
- Tracker-konvention: `Type:`, `Status:` och `Blocked by:` högst upp i varje
  ticket; svar skrivs under `## Answer`.
- Undantag från plan-only (2026-10-22): A2, Nya golden cases och
  Claim-extraktion krävde färdig implementation innan stängning. Commits:
  `8ece2c94` (A2), `ff52d1d7` (golden cases + seams), `e8bfb860`
  (claim candidates), `b2125e7e` (pair candidates + recall), `b6d4a196`
  (pair judgement + live measurement), `6b739e28` (five coverage levels),
  `0dc3c562` (A0 freeze), `93002f99` (measurement protocol), `72819568`
  (A1 route authority), `5f30d750` (arm comparison), `360400c2` (B0 shadow
  gap review), `fe53fd51` (B1 falsifiable gap hypotheses), `a201ae7d` (B1b
  hardened rejection), `f2e4580f` (B3 prioritisation interface + Recall@Budget
  ceiling), `7b4320c8` (B3b staged diagnosis), `52bb0725` (B3c live A/B arms),
  `6210b26c` (B4 hybrid candidate generation), `6b8d311b` (B4b full live
  hybrid arms), `ea60f8da` (B4c factorial), `18562447` (decision diagnostics),
  `73addf8c` (support root cause), `0b469d93` (stop shadow), `a6b609cb` (early
  stop arm), `ee4a0867` (facit v2 + QA). Hybrid är ny experimentstandard
  (ticket 25); B4c-arm D är referens. Existential early stop: 119 faktiskt
  undvikna Jev-anrop, 34 in-flight, 8,4 s väggtidsvinst, 0 ogiltiga stopp.
  Facit v2: 20 valida fall, D 40/40 mot korrigerat facit (litet känt material).
  Facit-QA v2b gör låg lexikal relation till granskningsvarning. SSR-förutsättning
  saknas: befintliga ankare är tone/style, ingen Overgraph- eller klausul-
  implementation finns. Arkitekturplan för gemensamt ankarbibliotek finns i
  `docs/architecture/ssr-clause-pr-review.md`. PR #428 är **mergad** som
  `77b8ded8` efter fix `ca68ad0d`; PR #429 är **mergad** som `0a3848e0` efter att
  SQL-klausulvägen tagits bort. Overgraph är enda persistens-/sökmotor för
  klausuldomänen. Ticket 41/42 är påbörjade: 140 granskningskort (35 avtal ×
  4 kategorier) är genererade men INTE facit. Backendprestanda är mätt på 35
  ingästa avtal (PR #430): kall fyllning ~12,1 s, varm ~0,62 s, ny kolumn ~4,45 s,
  första-rads-proxy ~0,04 s; profilering visar att cachegriddens score/objektbygge/
  persist dominerar, inte Overgraph-läsning. Ingen UI- eller kvalitetsmätning.
  Protokoll i
  `docs/architecture/tabular-review-benchmark-v1.md`. Produktionen är orörd.

## Decisions so far

<!-- En rad per stängd ticket: namn, gist, länk. -->
- [Inventera befintliga faktapar- och konfliktmekanismer](issues/01-inventera-faktapar-och-konfliktmekanismer.md): Explicit faktapar är bara mätta i labbkoden (16/16, openjev-0.1); duplicate-score och oberoende är okopplade och en persistent konfliktpost saknas.
- [Route-auktoritetens omfattning (A1)](issues/03-route-auktoritet-a1.md): `sufficient` kräver gate PASS **och** explicit `final_outcome=sufficient` (4-signal auktoritetspredikat); PASS+uncertain/insufficient → insufficient, ogiltig route → failed, programmatic-vägen undantagen. A1 löser inte kontradiktionsfällorna.
- [Konfliktmodell och lösningsprovenance (A2)](issues/04-konfliktmodell-a2.md): Konflikter är typade records med `unresolved`/`resolved`/`not_applicable`; endast verifierbar temporal/entitet/definition/supersession får lösa, okänd motpart aldrig. Duplicate/oberoende är separerade; replay 0.95 mot 0.61/0.89/0.94 förblir unresolved. Implementerat och testat i `8ece2c94`.
- [Nya golden cases för A1–B](issues/05-nya-golden-cases.md): Sex konfliktfall med låst A2/A3-matris, två experimentella test-seams (scripted score-overrides, counterparts) och full-workflow-verifiering. A0:s fyra benchmarkfall orörda; implementerat i `ff52d1d7`.
- [Claim-extraktion för A3](issues/06-claim-extraktion-a3.md): Deterministiska claim-kandidater (inte fakta) med exakt offset-invariant, `extracted`/`uncertain`/`unprocessed`, kanonisk nyckel endast för gruppering, metadata endast från provenance. Budgettak markerar ofullständig täckning och blockerar `sufficient`; implementerat i `e8bfb860`.
- [Kandidatgenerering för faktapar (A3)](issues/07-kandidatgenerering-a3.md): Fryst par-facit; A/B/C mäts separat med recall före och efter 40-parsbudget. A 1.00/1.00 (44 par, 0 anrop), B 1.00/0.80 (tailparet rank 340 → bort), C 1.00/1.00 (48 par, 5 embeddinganrop); inga Jev-anrop. `canonical_key` exkluderar aldrig. Implementerat i `b2125e7e`.
- [Jev-protokoll och SWE-form för faktapar (A3)](issues/08-faktaparsprotokoll-a3.md): Jev bedömer valda par i huvudworkflowens map-noder. `CONTRADICTS`/`SCOPE_DIFFERENCE` blir konfliktkandidater som A2 avgör; `COMPATIBLE` aldrig; `INSUFFICIENT` = uncertain, tekniska fel = unevaluated och blockerar sufficient. Live: deterministic 1.00/1.00, embeddings 0.67/0.50, hybrid 1.00/0.67; 4 falska motsägelser i embeddings/hybrid. Implementerat i `b6d4a196`.
- [Täckningsmätning på fem nivåer](issues/09-tackningsmatning.md): Fem separata nivåer med explicit kontroll och gate-flagga, ingen samlad procentsiffra. Conflict-facit gatar endast i benchmark; utan facit `not_measured`. Tail-fallet: facitparet hittat men 15 717 par föll på budget → coverage incomplete → blockerar sufficient. Implementerat i `6b739e28`.
- [Frys A0-baslinje och golden cases](issues/02-frys-a0-baslinje.md): A0 fryst vid `b55eae13` med två live-rep (`jev-1.14.0`, 1 043 försök/rep) och råartefakter. Två transienta JevClientError per rep gjorde att `late_evidence` föll i rep 1 men inte rep 2: A0 är ett intervall (accuracy 0.75 vs 0.50). `0dc3c562`.
- [Mätprotokoll för armarna](issues/10-matprotokoll.md): Semantisk kvalitet på rena körningar (tekniska fel exkluderas, aldrig detektion), operativ kvalitet över alla live-rep, parad kassett-replay, fem coverage-nivåer med execution vs semantic, tre par-tillstånd, kostnadsmått och förregistrerade PASS/FAIL. A0 orörd; parbudget 40. `93002f99`.
- [Implementera route-auktoritet (A1)](issues/13-implementera-route-auktoritet-a1.md): `final_outcome` + fyra-signalers auktoritet; PASS+uncertain/insufficient blir aldrig sufficient, FINISH utan utfall fail-closed, programmatic undantagen. Arm-toggles för A0/A1/A2/A3 + scriptat A0-vs-A1-artefakt. `72819568`.
- [B1b – Härda gap-kontraktet och negativa fall](issues/18-b1b-hardning.md): sluten ankarmängd, fel-need-ankare avvisas, 5 syntetiska fall, förregistrerade mått. Narrative TP4/FP6 (prec 0.40) mot deterministisk TP4/FP5 (prec 0.44); incremental yield 0, false workflow 0.875, unsupported anchor 0.125 → **END_NARRATIVE_BRANCH**. B2 avvecklad; B3 prioriterad. `a201ae7d`.
- [B1 – Shadow-jämförelse av narrativ precheck](issues/15-b1-shadow.md): fyra gap-utfall, strukturerade hypoteser, deterministisk ankervalidering och noll-LLM-baseline. Narrative TP2/FP4/FN0/TN1 (prec 0.33, recall 1.00) mot deterministisk TP2/FP2/FN0/TN3 (prec 0.50); `late_evidence` hittas, `short_sufficient` förblir NO_GAP, men 2 av 10 VERIFIED_GAP hade påhittade ankare → acceptansen fallerade. B2 blockeras. `fe53fd51`.
- [B-instrumentering: narrativ precheck](issues/11-b-instrumentering.md): B är ett mätbart verktyg utan beslutsrätt; begränsad workflow-allowlist, experimentprompt, separata mått för detektion/täckning/beslutskorrekthet. B0 live: hittar förväntat gap (1/1) men flaggar 10/10 fall och 9/9 negativa → överflaggar; B1 kräver skärpt gap-facit. `360400c2`.
- [Kör armjämförelsen enligt protokollet](issues/14-kor-armjamforelse.md): 10 fall, 2 live-rep/arm, ordning A0→A2→A3→A1. A3 accuracy 0.73 / false-sufficient 0.00 (A0 0.24/0.82); tail/duplicate/independent löses av verklig detektion, late endast av ofullständig coverage (fail-closed). +170 Jev-anrop vs A0, 384 anrop per upptäckt motsägelse. A1/A2 6 reproducerbarhetsgap var; A3 95 nya/live-anrop. `5f30d750`.

## Not yet specified

- Exakt artefaktformat och versionering för arm-jämförelser (beror på
  mätprotokollet).
- Om det utökade facit behöver en andra oberoende labelrunda eller domare.
- Svårare semantiskt tail-fall (motsägelse utan tokenöverlapp) i nästa
  benchmarkversion, för att pröva om embeddings tillför recall utöver A.
- Om 40-parsbudgetens process-coverage ska vara acceptabel på stora underlag,
  eller om budgethanteringen ska ändras (hör till mätprotokollet).
- Välja parstrategi som standard efter mätprotokollet; deterministisk tills
  vidare, inte låst som vinnare.
- Om en verktygsanropande B-arm är en egen framtida konfiguration eller ska
  förkastas.

## Out of scope

- Implementation, kodändringar och live-körningar för fas 1–6: lämnas över efter
  att kartan stängts (valt mål: beslutscomplete plan).
- Cutover/inkoppling av produktionsassessorn (`build_llm_research_assessor`,
  `LlmResearchAssessor`).
- Ersättning av researchens SWE-loop; ny generell agentplattform; ny graf- eller
  evidensdatabas.
- Ändringar av produktionsprompts, TTL/revalidation, kundkompatibilitet; dolda
  modell-fallbacks.
- Automatisk merge; ändringar i PR #426 som bieffekt.
- Ändring av produktionsklassificeraren `classify_research_decision` /
  `would_short_circuit`: A1:s 4-signal-auktoritet är experimentlokal och får inte
  smyga in i produktionsvägen (divergensen granskas i slutgranskningen).
