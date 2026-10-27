# SWE Gym v2 — granskning, arkitektur och experimentdesign

> Svar på specifikationen "SWE Gym v2 – Reinforcement Learning för Sweycoin-budgetering" (§11, Uppdrag till DeepSeek).
>
> Status: granskningsunderlag. **Ingen implementation förrän planen granskats** (spec §11). Allt som föreslås här bygger på den existerande implementationen i `crates/swe-gym` (PR #435, #436) och den reella research-motorn i `backend/app` — ingen ny motor, inga parallella system.

## 1. Bedömning i korthet

- **Omformuleringen är rätt.** V1 ställde frågan "i vilken ordning skannar vi chunks", och där uppmätte vi att värdet låg i den deterministiska ordningen (arm H stängde nästan hela gapet till oraklet) medan RL:s marginalvärde var ≈ 0. V2 frågar istället "hur fördelar vi budget över strategier med olika kostnads-/kvalitetsprofiler" — en bredare problemklass där inlärning har en reell chans. Det är exakt rätt slutsats av våra egna data.
- **Det mesta finns redan.** Ledgern (inklusive virtuell reward-pool som aldrig kan spenderas), frysta bänkar, fixture-providers, SARSA/TD(0) och banditer finns i craten. V2 är tre nya moduler i samma crate, inte ett nytt ramverk.
- **Den verkliga risken är inlärningsbarhetsgapet** — att miljön saknar struktur att lära sig, och experimentet upprepar v1:s null-resultat. Därför bygger planen på en **kalibreringsgrind**: mät att signalen finns (orakel > baslinjer med marginal) *innan* vi tränar RL. Det är v1:s viktigaste metodläxa ("measure signal first") omsatt i experimentdesign.
- Specen är i stort klok. Fem justeringar föreslås i §12 (action-redundans, gles belöning, algoritmordning, A-armen som tvåfasscanner, kostnadskalibrering).

## 2. Fråga 1 — MDP, SMDP eller något annat?

**Svar: diskret-tids MDP över beslutsepoker.** SMDP behövs inte i POC:en.

- Varje `step` = ett budgetbeslut. Segmentutfallet (faktisk förbrukning, framsteg, delresultat) viks in i transitionen till nästa observation. Det gör miljön till ett vanligt episodiskt MDP med finit horisont (budgettak + max steps).
- SMDP/options-formulering blir relevant först om vi senare vill *tidsdiskontera* wall-clock eller modellera långa strategisegment som egna policies. Inget av det behövs för att pröva hypotesen — belöningen straffar kostnad direkt (`−actual_cost`), inte tid.
- **Gratis orakel i den syntetiska miljön:** eftersom SyntheticEnv är ett känt MDP (tabellstyrda parametrar) kan vi beräkna den exakt optimala policyn med värdeiteration över det diskretiserade tillståndet. Det ger oss v1:s C\*-motsvarighet i v2: en diagnostisk övre referens som också ger `difficulty_weight`-skattningar offline (se §5).

## 3. Fråga 2 — Algoritm

**Svar: feature-linjär SARSA(λ) först; PPO/discret actor-critic som jämförelsearm — inte som utgångspunkt.**

1. **Primär lärande arm: linjär Q/SARSA med handbyggda, ortogonala features** (återanvänd `td.rs` episodisk kredit; bygg på v1:s SARSA).
2. **Debug-referens: grovt tabulärt Q** över en liten nyckeltillståndsmängd (budget-bracket × per-strategi-framstegsnivå). Tabulärt är granskningsbart och avslöjar om features förstör något.
3. **PPO/discrete actor-critic:** senare jämförelsearm, först när kalibreringsgrinden passerats och vi ser att funktionsapproximation över t.ex. embedding-features tillför något.

Motivering, grundad i v1:

- v1 lärde oss att parametriska lager inte slog tabulärt/linjärt när signalen var svag — linjär SGD kollapsade på kollinära brusfeatures och det tabulära banditskiktet vann. Slutsatsen var inte "RL är fel", utan "algoritmvalet ska matcha signalstyrkan".
- POC:ens action-rymd är liten (~19 handlingar) och tillståndet kan sammanfattas i ~20–30 ortogonala features. Joint-tabulärt över *hela* tillståndet exploderar (budget × status³ × förbrukning³ × …), så ren tabularism går inte; deep RL behöver tusentals episoder och ger sämre granskningsbarhet. Linjär SARSA med ortogonaliserade features är mittpunkten.
- Specens förslag om minibatch (erfarenhet per fråga, uppdatering var 20:e, säsong 200, valideringsgenerationer, orört testset) antas som konfigurerbara defaultvärden.

## 4. Fråga 3 — Gym-liknande miljö i Rust

**Svar: ett minimalt `env`-trait i befintlig crate. Inget externt gym/RLLib — det vore en ny motor och strider mot beroendepolicyn.**

```rust
trait SweEnv {
    fn reset(&mut self, question: &Question) -> Observation;
    fn step(&mut self, action: Action) -> (Observation, RewardMilli, Done, Info);
}
```

- **`SyntheticEnv`:** tabellstyrd (per strategi: kostnad per steg, framstegssannolikhet per frågetyp, avtagande avkastning, kvalitetstak). Determinism givet (fråga, frö) — v1:s frö-läxa (fryst RNG-klon) kodas in som test. Ersätter/utökar `gen.rs`.
- **`RealEnv`:** exekverar strategisegment via swe-native `Machine` mot provider-trait:en (`FakeCorpus` offline, `HttpJev`/`HttpLlm` live env-gated, `Record`/`Replay` för frysta fixtures). Samma trait, samma determinismkrav i replay-läge.
- Krav: ogiltiga handlingar maskeras (spec §5.2), varje step bokförs i ledgern, och hela episoden kan återskapas från eventloggen (reproducerbarhet — cratens non-negotiable #4).

## 5. Fråga 4 — State, actions, reward, terminering

**State (observationen — aldrig facit):**

| Feature | Representation |
|---|---|
| Frågetyp | embedding-kluster (v1:s verktyg; syntetiskt: genererad typ) |
| Återstående Sweycoins | diskret bracket |
| Per strategi: status | {ej startad, aktiv, pausad, stoppad} |
| Per strategi: förbrukat | diskret bracket |
| Per strategi: bästa delresultat | nivå {0..3} + avtagande-flagga (senaste Δ < föregående) |
| Steg räknat, cache-status | skalärer |

`difficulty_weight` finns **inte** i observationen — den är en pre-registrerad miljökonstant (syntetiskt: miljöns parametrar; verkligt: offline-metadata, t.ex. oraklets scankostnad från v1-fixtures, fryst i bänk-JSON:en). Det stänger dörren mot att agenten manipulerar sin egen svårighetsvikt.

**Actions (diskreta, maskerade):**

- `INVEST(strategi, {1, 5, 10, 20})` × 3 strategier = 12
- `PAUSE(strategi)` × 3, `STOP(strategi)` × 3
- `FINISH`

= 19 handlingar. **`CONTINUE`/`START` kollapsas in i `INVEST`** (INVEST på aktiv strategi = fortsätt, på ny = start). **`TRANSFER` skjuts upp** — det är uttryckbart som STOP+INVEST, och kredittilldelningen över transfers är en egen fälla som inte ska belasta POC:en (specens §9-POC har heller inga transfers).

**Reward — gles, terminal:**

- 0 under episoden.
- Vid `FINISH` eller budgetslut: `R = difficulty_weight × verified_quality × base_reward − total_cost`.
- `total_cost` läses från ledgerns `spend`-event — aldrig från planen (single source of truth).
- `verified_quality` räknar bara **förstagångsny verifierad evidens**; dubbletter ger 0 (anti-farming, spec §6).
- **Ingen bonus för oanvänd budget** — den är redan implicit i `−total_cost`; en +leftover-term vore dubbelräkning.
- Delbelöningar för ny evidens byggs som en **A/B-knapp i SyntheticEnv, avstängd som default**. V1:s shaping-fälla är dokumenterad: myopisk formning gav 84–210/500, episodisk kredit 325/500. Det ska inte återupplevas.

**Terminering:** `FINISH` · budget slut · facit löst (täckningskravet uppfyllt) · max steps (fast litet tak — v1:s max_steps-läxa).

## 6. Fråga 5 — Ledger-koppling

**Specens hårdaste krav är redan implementerat och testat.** V1-ledgern (ledger.rs) har som invariant 4 att `Reward` bokförs i en separat virtuell pool som aldrig påverkar `available` — virtuella belöningar kan aldrig spenderas, alltså aldrig skapa verklig exekveringsbudget. Event:en har redan `run_id` → episod-scoping är gratis.

V2 tillägg:

1. Episod-konton: en `allocate` per fråga, agentens strategisegment `reserve`/`spend` mot det kontot.
2. `actual_cost` i belöningen = summan av episodens `spend`-event.
3. Beslutshistoriken (spec §9 kriterium 5) = eventloggen; `Ledger::replay` återskapar trajektorian.
4. Nytt invariant-test: "reward-pool kan aldrig bli föremål för `allocate`/`transfer` till exekveringskonton".

Produktionssidan (endast efter ett explicit promotingsbeslut — cratens exit criteria): budgetförvaltarens beslut är SWD-noder (decision/map) i swe-native-kerneln; run-persistens återanvänder `WorkflowRunStore`; budgetknapparna motsvarar `loop_control.ResearchWaveConfig`. **Inga nya tabeller, inga nya tjänster.**

## 7. Fråga 6 — Träning: syntetiskt, fryst, verkligt

- **Fas 0 — Kalibreringsgrind (syntetisk):** orakel > bästa baslinje med pre-registrerad marginal på hållna frågor. Misslyckas grinden är miljön omdesignad — vi tränar inte RL mot en miljö utan signal. Detta är v1:s null-lärdom operationaliserad.
- **Fas 1 — Syntetisk träning:** tusentals billiga episoder; erfarenhet per fråga, minibatch var 20:e, valideringsgeneration, orört syntetiskt testset sist.
- **Fas 2 — Frysta fixtures = utvärdering, inte RL-träningsdata i POC:en.** Specens varning är korrekt: replay kan inte prediktera utfall av beslut som aldrig exekverades. Offline-RL från replay kräver en utfallsmodell (t.ex. SyntheticEnv kalibrerad mot verkliga data) — det är en framtida arm, inte POC.
- **Fas 3 — Verkliga körningar:** budgettakade, env-gated (v1:s live-disciplin). Syntetiska och verkliga siffror redovisas alltid åtskilda (cratens non-negotiable #1; spec §8 säger samma sak).

## 8. Fråga 7 — Risker

| Risk | Mekanism | Motåtgärd |
|---|---|---|
| Reward hacking: svårighetsvikt | Agenten manipulerar features som styr `difficulty_weight` | Vikten pre-registrerad/offline, aldrig i observationen |
| Reward hacking: dubblett-farming | Upprepad evidens ger upprepad kredit | Novelty-gating: bara förstagångsny evidens räknas |
| Reward hacking: bluff-FINISH | Tidig avslutning med partiell kredit | Terminalbelöningen kräver verifierad kvalitet; inga shaping-bonusar som default |
| Kostnadsunderrapportering | Agenten "sparar" genom att inte rapportera kostnad | Kostnad läses från ledgern (trusted executor, idempotent) |
| Överanpassning | 5 verkliga frågor → policyn memorerar | Låg kapacitet (linjär/tabulär), hållna frågor, ≥3 frön, per-frågetyp-rapportering |
| Generaliseringsgap syntetisk→verklig | Syntetisk miljö för snäll | Domänrandomisering i SyntheticEnv; verklig bänk är slutdomaren |
| Inlärningsbarhetsgap | Miljön saknar struktur att lära | Kalibreringsgrinden upptäcker det billigt; null är en giltig, publicerbar utgång (v1-precedens) |
| Bokföringsbuggar | Virtuella belöningar läcker in i budget | Ledger-invarianter + nya tester (§6 punkt 4); replay-verifikation |

## 9. Fråga 8 — Första experiment med acceptanskriterier

**Miljö:** SyntheticEnv v1 — 3 strategier A/B/C, 100 Sweycoins, 3+ frågetyper med distinkta optimala allokeringar (typ 1 → A, typ 2 → B, typ 3 → C, typ 4 → blandad A→B) + inbyggd avtagande avkastning. Parametrar i JSON-konfig, fröstyrt.

**Armar:** lika fördelning · sekventiell deterministisk prioritet · heuristisk adaptiv · orakel (värdeiteration, diagnostisk) · tabulär bakåt-Q-lärande arm (se 11.1).

**Träning:** säsonger om 800 frågor (200/typ — specens 200 visade sig för litet för tabulära armen, se 11.1), minibatch var 20:e, 3 frön. **Utvärdering:** 8 hållna syntetiska frågor (osedda budgets 60k/140k) + de 5 frysta verkliga frågorna (utvärdering endast, steg 6).

**Acceptanskriterier (pre-registrerade):**

1. *Kalibreringsgrind:* orakel > bästa baslinje med ≥ 10 % marginal på hållna frågor — annars omdesignas miljön och RL tränas inte.
2. *Inlärningsbarhet:* SARSA ≥ bästa baslinje i genomsnittlig verifierad kvalitet per Sweycoin (pre-registrerat parat test, ≥ 3 frön).
3. *Budgettak:* 0 överskridanden i samtliga episoder (ledger-invariant).
4. *Reproducerbarhet:* `Ledger::replay` återskapar identisk trajektoria och belöning.
5. *Verklig bänk:* ingen regression mot lika fördelning på de 5 frågorna; syntetisk framgång ensam är inte godkänt.
6. *Beslutshistorik:* varje budgetbeslut är en replay-bar event (spec §9 kriterium 5).
7. *Belöningsisolering:* virtuella belöningar kan aldrig `allocate`as eller `transfer`as till exekveringskonton (test).

## 10. Arkitektur och återanvändningsmatris

Nya moduler i `crates/swe-gym`: `env.rs` (trait + SyntheticEnv + RealEnv), `agent.rs` (baslinjer + lärande armar), `train.rs` (episodloop, minibatch, validering). Utökningar: `ledger.rs` (episod-scope-hjälpare), `benchmark.rs` (env-konfigfält i bänkformatet), `calibrate.rs` (grinden), `main.rs` (subkommandon). Inga nya crates, inga nya tabeller, inget under `backend/app` — importriktningen är orörd (cratens non-negotiable #6).

| Behov (spec) | Befintlig motsvarighet | Beslut |
|---|---|---|
| Sweycoin-ledger | `ledger.rs` (event-log, idempotens, replay, virtuell reward-pool) | Återanvänd + utöka |
| Strategiexekvering (segment) | swe-native `Machine` + `strategy.rs`-armar A–H | Återanvänd som segment-byggstenar |
| JEV/LLM-anrop | `provider.rs` trait + `Fake/Http/Record/Replay` | Återanvänd |
| Frysta bänkar/fixtures | `benchmark.rs`, `bench_v1.json`, `bench_real_v2.json`, `real_fixtures/` | Utöka formatet med env-fält |
| Inlärningskärna | `td.rs` (SARSA, episodisk kredit, MIN_SAMPLES) | Återanvänd/utöka |
| Syntetisk värld | `gen.rs` | Ersätts av `env::SyntheticEnv` (samma dataflöde) |
| Orakel | v1 C\* (diagnostisk) | Ny variant: värdeiteration (exakt i syntetisk miljö) |
| Run-persistens (produktion) | `WorkflowRunStore` (overgraph) | Återanvänd vid ev. policy-export |
| Budgetknappar (produktion) | `loop_control.ResearchWaveConfig` | Återanvänd som policy-export-mål |
| Gym-plattform / RL-bibliotek | — | **Ny: env-trait ~50 rader** — motivering: specifik miljö, ingen generell motor; externt RL-ramverk strider mot beroendepolicyn (SARSA är ~100 rader att skriva själv) |

## 11. Genomförandeplan (grindstyrd)

Implementeras först efter att denna plan granskats. Varje steg stängs med tester.

1. **Ledger-utökning:** episod-scope + de två nya invariant-testerna (§6). *Grind:* `cargo test`.
2. **`env.rs`:** trait + SyntheticEnv + determinism-/maskeringstester + orakel via värdeiteration. *Grind:* determinism- och orakel-korrekthetstester.
3. **Baslinjer + eval-harness** (återanvänd benchmark-drivern). *Grind:* baslinjerna kör på bänkformatet.
4. **Linjär SARSA + grov tabulär referens.** *Grind:* enhetstester mot en känd liten MDP med känt optimum.
5. **Kalibreringsgrind + syntetisk träning + valideringsrapport.** *Grind:* acceptanskriterier 1–4.
6. **Fryst verklig bänk + rapport + beslutspunkt** (cratens exit criteria). *Grind:* kriterier 5–7.

### 11.1 Status — steg 1–5 implementerade och testade (2026-10-26)

Implementation: `crates/swe-gym/src/{env,agent,oracle,train}.rs`, tester i `tests/env_tests.rs` (12 test), körbar rapport `cargo run --example v2_synthetic`. Oraklet är exakt DP över det diskretiserade tillståndet (budget × tiers); learen är **tabulär bakåt-Q-learning med per-stegs-belöningar och UCB-explorering**. Tre designfynd från implementationen, alla uppmätta och dokumenterade i koden:

1. **Belöningen måste vara per steg, inte netto vid slutet.** Specens nettoformel `quality×base − total_cost` gör tillståndet (tiers) icke-Markovskt — två vägar till samma tiers har olika total_cost. Med nettoformeln kollapsade Q-värdena (learner 47k < baslinje 95k). Fix: `−cost` debiteras vid varje INVEST, `quality×base` vid FINISH; summan är identisk med nettoformeln (testat), och tillståndet blir Markovskt.
2. **Budget-bracket togs bort ur learens tillstånd.** Budget spelar bara roll via maskering; med bracket blev tabellen 4× glesare än sampelbudgeten (learner förlorade pengar).
3. **Bakåt-Q-learning med α=1 och UCB-bonus** — kedjekrediten propagerar i ett genomlöp och explorationen når djupa tillstånd som greedy aldrig besöker (v1:s feedback-starvation, igen). α=0.2 dämpade kedjekrediten med α^n och lärde aldrig tvåstrategi-mixar.

**Uppmätta siffror (syntetisk, deterministisk miljö; held-out = 8 osedda frågor, budgets 60k/140k):**

| Arm | Held-out medelvärde |
|---|---|
| lika fördelning | 95 312 |
| sekventiell | 84 062 |
| heuristisk adaptiv | 99 062 |
| **mc-q-learner** | **128 500** |
| orakel | 132 500 |

Not: den adaptiva baslinjen fick en platå-stoppregel efter att steg 6 avslöjat att EMA-regeln aldrig når exakt 0 och därför aldrig slutar (49k → 99k; learen vinner fortfarande, testerna om-pinnade).

Kalibreringsgrinden: orakel / bästa baslinje = 1.39 (krav ≥ 1.10) ✓ · learen 97 % av orakel ✓ · kriterier 1–4, 6, 7 gröna i CI-tester. Kriterium 5 (verklig bänk) kvarstår — steg 6, utvärdering mot de frysta verkliga frågorna.

Per fråga (learner vs orakel): t0 80k/80k, t1 130k/130k, t3 190k/190k — gap 0. Hela gapet ligger på t2 (114k/130k): där når B4+C2 redan kvalitetstaket (1.0) och den sista marginalinvesteringen är nära break-even — learen tar den, oraklet gör det inte.

### 11.2 Status — steg 6: fryst verklig bänk (2026-10-26)

Implementation: `src/real.rs` (RealEnv över den frysta bänken + verkliga baslinjer), tester i `tests/real_env_tests.rs` (6 test), körbar rapport `cargo run --example v2_real`.

RealEnv-design: A = JEV-scan i likhetsordning (arm H:s motor, 1 coin/chunk), B = JEV-scan i dokumentordning, **C = LLM maskerad** (fryst data saknar deep-svar — dokumenterad begränsning, högljutt inte tyst). Framsteg = fynd per strategi (facit-fritt, v1:s ScanState.found). Kvalitet = fynd/required, bara vid episodslut. Allt via ledgern med per-stegs-bokföring; `settle` frigör ospenderad rest. Frågetyp = pre-registrerad observerbar regel (chunk-count-buckets) — en proxy, avsiktligt inspelad innan resultaten fanns.

**Uppmätta medelvärden (5 frysta frågor, budget 200 coins/fråga):**

| Arm | Medel netto |
|---|---|
| real-adaptive (fynd-platå) | +44 000 |
| real-equal-split | +22 000 |
| real-sequential (likhet först) | +20 000 |
| **mc-q-learner (syntetiskt tränad)** | **−9 303** |

**Kriterium 5: UNDERKÄNT — learen regresserar mot lika fördelning på den verkliga bänken.** Detaljen: learen hittar full täckning på alla fem frågorna men stoppar för sent — dess stoppbeslut är inlärt mot syntetiska tier-dynamiker som den verkliga miljön inte producerar. (Före självloop-fixen i §13 brände den hela budgeten, −100k; efter fixen −9.3k — samma utslag, mildare magnitud.) Överföringsfelet sitter i stoppbeslutet, inte i att hitta evidens.

Tre dokumenterade överföringsblockerare: (1) frågetyp-regeln är en godtycklig proxy — syntetiska typer har ingen semantisk motsvarighet i verkliga drag; (2) tier-semantiken (0–4 per strategi) kan inte uttrycka det verkliga framstegssignalen (fynd-antal) — verkliga baslinjer behöver `obs.found`; (3) den verkliga bänkens lärbara marginal är densamma som v1 mätte: ordning (arm H 38/26/47/18/16 vs C\* 20/13/34/13/7 scans), inte budgetallokering över strategier — med bara en bra strategi och en dominerad finns ingen allokeringsstruktur att lära.

**Korrigerad slutsats (efter granskning):** det som mätts är att *överföringen* från syntetisk träning till verklig miljö misslyckades — **inte** att idén om en lärande budgetförvaltare är falsifierad. Två skäl till att slutsatsen inte får dras längre: (1) den frysta bänken har bara **en** förmåga med data (JEV-scan; deep/LLM saknas), så nivå-2-frågan — allokering *mellan* retrieval/JEV/LLM — kunde aldrig ställas där; (2) stoppmisslyckandet är ett gränssnittsfel: learen tränade mot tier-semantik som den verkliga miljön inte producerar, och dess tillstånd saknade den signal (fynd-platå) som ett rationellt stoppbeslut kräver. Nästa steg är därför inte att avsluta spåret utan att bygga nivå-2-gymmet med tre genuint olika förmågor — se §12.

## 12. Punkter i specen att justera före implementation

1. **§5.2 Action-redundans:** `INVEST`/`CONTINUE`/`START` → en `INVEST`; `TRANSFER` skjuts upp till efter POC (kredittilldelning över transfers är en egen fälla).
2. **§6 Gles belöning som default:** delbelöningar som A/B-knapp, inte grundutförande — v1:s shaping-fälla (84–210/500 → 325/500 med episodisk kredit) är dokumenterad i `docs/SWE_Sweycoins_resultat.md`.
3. **§7 Algoritmordning:** PPO/actor-critic som jämförelsearm efter kalibreringsgrinden, inte som utgångspunkt — v1 visade att enkla skikt vinner när signalen är svag.
4. **§9 POC A-arm:** A bör vara v1:s tvåfasscanner (arm H) — retrieval-ordningen stod för nästan hela vinsten på den verkliga bänken; det är den realistiska retrievalstrategin.
5. **§4 Kostnadstabell:** kalibrera mot uppmätt förbrukning i v1:s fixtures istället för platshållarvärden; indexets capital accounting finns redan (78 coins engångskostnad).
6. **§10 Modellmarknad:** rätt att hålla utanför POC; notera att ledgerns `transfer`/`reward`-konton redan är byggstenen för virtuella portföljer när den fasen kommer.

## 12. Två nivåer: budget och strategi — och nästa experiment

**Arkitekturfrågan (fördelar RL mellan färdiga workflows, eller investerar den i enskilda operationer inuti ett workflow?): båda — på två nivåer med en hård söm.**

- **Nivå 1 (inuti ett workflow):** vilken chunk som skannas härnäst, när JEV kontra lookup, eskaleringströsklar. Högfrekventa, billiga beslut. Policy: fast och beprövad — arm H:s tvåfasscanner. (V1 mätte att RL:s marginalvärde här ≈ 0.)
- **Nivå 2 (mellan workflows/förmågor):** `INVEST(förmåga, belopp)`, paus, stopp, avsluta. Lågfrekventa, dyra beslut — budgetförvaltarens hela jobb.
- **Sömmen = förmågans gränssnitt:** `invest(amount) → {kostnad, framsteg, delresultat}`. Budgetförvaltaren lär sig förväntad förbättring per coin per förmåga per frågetyp — aldrig *hur* JEV skannar ett dokument. Exakt användarens skiss: RL Budget Manager ovanpå Retrieval/graf, JEV/analys, LLM/research, med kvalitet/kostnad/framsteg/belöning tillbaka, och verifierat resultat + ledger under.
- Produktionsmotsvarighet: budgetrader i `loop_control.ResearchWaveConfig` (budgetförvaltarens söm), `fast_controller` (JEV), `result_store`/`answer_graph` (verifierade resultat), ledgern (kostnad).

**Nästa experiment — nivå-2-gym med tre genuina förmågor (implementerat, `env::capability_config`):**

- A = retrieval/graftraversering (billig, kvalitetstak 0.5 — hittar evidens, resonerar inte), B = JEV-analys (mittenpris, tak 0.75 — verifierar), C = narrativ LLM (dyr, tak 1.0 — resonerar). Per-tier-kostnader som stiger → avtagande marginalavkastning, dvs. den mättnadssignal ett stoppbeslut kräver.
- Fyra frågetyper med distinkta optimala mixar (DP-verifierade): t0 retrieval-ledd A3+B2+C1, t1 JEV-ledd B4+C1, t2 LLM ensam C4, t3 balanserad A3+B2+C1. **Ingen strategi är alltid bäst.**
- Facit finns bara i terminalbelöningen — aldrig i observationen (kvalitet avslöjas vid episodslut).

**Uppmätt (held-out = 8 osedda frågor, budgets 60k/140k):**

| Arm | Medel |
|---|---|
| lika fördelning | 58 750 |
| sekventiell | 35 625 |
| adaptiv (med platå-stopp) | 58 750 |
| **mc-q-learner** | **81 250** |
| orakel | 86 250 |

Grind: 1.47 (krav ≥ 1.10) ✓ · learen 94 % av oraklet ✓ · **stoppbeslutet: learen spenderar 150k mot oraklets optimala 110k (kvot 1.36, acceptans ≤ 1.5)** — den lär sig alltså att sluta nära optimalt när tillståndet bär mättnadssignalen. Tester: `tests/capability_tests.rs` (4 st, pinnade), rapport: `cargo run --example v2_capabilities`.

Lärdom på vägen: den "enkla adaptiva regeln" var degenererad — EMA-marginalen når aldrig exakt 0, så regeln investerade tills budgeten tog slut (medel 0). Med platå-stopp (3 no-gain → avsluta) blev den 58 750. Samma bugg fanns i RealEnv:s adaptiva baslinje och fixades där. Det är en bra påminnelse om varför baslinjerna måste vara lika genomtänkta som learen.

**Nästa steg:** först när detta fungerar i syntetiska scenarier som liknar verkliga researchförlopp (kalibrerade mot uppmätta fynd-dynamiker, se 11.2), går vi till verkliga Golden Questions — och då krävs ny fryst data för LLM-förmågan (live-capture, env-gated) eftersom den befintliga bänken bara täcker JEV.

## 13. Synergi-experimentet: kompletterande förmågor och fördröjd belöning

Det sista syntetiska experimentet innan gymmets arkitektur fryses. Skillnaden mot §12: här **förändrar en investering i A värdet av en senare investering i B** — fördröjd avkastning, inte bara olika kostnads-/kvalitetsprofiler.

**Världen (`env::synergy_config`):** A = retrieval (hittar källor; **noll direkt kvalitet** — ren unlock), B = JEV (extraherar evidens; **4× dyrare per tier tills A hittat källorna**), C = LLM (syntetiserar; bidrar bara i mån av extraherad evidens: `cap × min(tC, tB)/4`). Typer: t0 kedjan lönar sig, t1 retrieval lönar sig inte (A prissatt över besparingen), t2 full syntes krävs, t3 lätt unlock räcker. Facit finns bara i terminalbelöningen.

**Pipeline:** online-säsong (200/typ) → **deterministisk täckningssvep** (400/typ; minst-besökta-handling-regeln är frö-oberoende) → **offline replay-fit** (värdeiteration över alla insamlade episoder till konvergens). Två lärdomar som krävdes:

1. **Självloop-biasen (γ=1):** en no-gain-investering bootstrappar från sitt eget tillstånds max och kunde slå Finish — learen loopade 22 no-gain-investeringar på skip-A-typen. Fix: γ=0.999 (späder 10-stegskedjor ~1 %). Om-pinnat i alla sviter.
2. **Frö-lotteriet:** online-exploreringens täckningsluckor gjorde greedy-policyn frö-beroende (29k–63k). Fix: täckningssvepen gör datatäckningen deterministisk; därefter är learen stabil över frön.

**Uppmätt (held-out = 8 osedda frågor, budgets 60k/140k):**

| Arm | Medel |
|---|---|
| sekventiell (pipeline A→B→C) | 12 812 |
| lika fördelning | 35 312 |
| adaptiv (platå) | 35 312 |
| **mc-q-learner** | **63 125** |
| orakel | 68 625 |

Grind 1.94 ✓ · learen **92 % av oraklet, 1.79× bästa baslinje** ✓ · stoppkvot 1.19 (≤ 1.5) ✓.

**Fördröjd-avkastningsbeviset (proberna, pinnade i tester):** på kedjetypen är learens **första investering retrieval (A)** trots att A ger noll direkt kvalitet (netto 65k mot oraklets 69k), och på skip-A-typen startar den med JEV (netto 57.5k = oraklet exakt). Den har alltså lärt sig *både* att betala för fördröjd avkastning *och* att hoppa retrieval när det inte lönar sig.

**Svar på frågan om marginalnytta:** ja — learen kan investera i samma förmåga flera gånger och observerar marginalnyttan via tier-tillståndet efter varje investering; Q-tabellen indexerar på (typ, tiers), vilket är precis byggstenen synergiinlärningen ovan utnyttjar.

**Beslut: gymmets arkitektur fryses här.** Nästa steg är verkliga Golden Questions — vilket kräver ny fryst data för LLM-förmågan (live-capture, env-gated), eftersom befintlig bänk bara täcker JEV.

## 14. Verklig benchmark: gemensamt observationsgränssnitt och två förmågor

Svar på granskningens två frågor, och den verkliga bänk de motiverade.

**Generaliseringsfrågan — ärligt svar:** täckningssvepen + värdeiterationen gör learen till en nästan komplett tabell över en *liten deterministisk syntetisk värld*. Det är en **kontroll** — den bevisar att signalen är inlärningsbar och att learen kan fånga fördröjd avkastning — men det är **inte** generalisering. Generalisering mäts bara på nya problem; det är den verkliga bänkens enda jobb.

**Framstegsfrågan — gränssnittet:** observationen bär nu det gemensamma interfacet för verkliga workflows (facit-fritt, allt beräknat från observerbara utfall):

| Fält | Betydelse |
|---|---|
| `spent_milli` / `remaining_milli` | faktiskt spenderat per förmåga / återstående budget |
| `found` / `new_evidence` | evidensobjekt totalt / sedan förra beslutet (källor = chunk-id:n) |
| `recent_hit_rate_bp` | fynd per 100 verifieringsanrop, rullande 20-fönster — observerad marginalnytta |
| `last_score_bp` | senaste verifieringens konfidens — osäkerhetsproxy |
| `pool_scanned` / `pool_total` | retrieval-poolens tillstånd |
| `contradictions` | 0 i fryst data (fältet finns för rikare fångster) |

Facit (kvalitet = fynd/required) avslöjas bara i terminalbelöningen — aldrig i observationen.

**Bänken (`src/real.rs` v2, `tests/real_env_tests.rs`):** två genuint olika förmågor med frysta, reproducerbara resultat: **A = retrieval** (50 milli/chunk, bygger kandidatpoolen i likhetsordning, noll direkt evidens) och **B = JEV** (1 coin/anrop, verifierar poolens topp mot 2019-fixturerna). JEV:s marginalnytta beror på poolen A har byggt — den verkliga fördröjda avkastningen. C = LLM maskerad tills deep-data fångats (live-capture, nästa steg).

**Uppmätt (5 frysta frågor, 200 coins/fråga):**

| Arm | Medel netto |
|---|---|
| real-equal-split | +22 000 |
| **real-pipeline-adaptive (stark baslinje)** | **+58 846** |
| mc-q-learner (syntetiskt tränad) | −29 200 |

**Utslaget:** RL-armen regresserar mot den starka baslinjen. Diagnosen är specifik och användbar: learen hittar evidensen (21/20, 15/13, 23/13 fynd på de frågor den jobbar på) men **stoppar för sent** — den bränner budgeten i tier-tillstånd som den syntetiska träningen aldrig besökte. Orsaken är **tillståndsgeometrin**: syntetiska tiers (0–4 per förmåga, beloppsdrivna) matchar inte verklighetens geometri (pool-kvintiler + fynd-takt), och frågetyp-proxyn (chunk-count-bucket) är fortfarande godtycklig. Allokeringskonceptet fälldes inte — gränssnittet mellan träning och verklighet gjorde det. Baslinjen använder det nya gränssnittet och vinner på att läsa `recent_hit_rate_bp` + pool-tillstånd.

**Slutsatsen för nästa steg:** en praktiskt användbar Sweycoin-förvaltare kräver att learen **tränas i det verkliga observationsgränssnittet** — vilket kräver verkliga träningskörningar (fler Golden Questions eller inspelade produktionskörningar) eller en syntetisk tvilling som speglar verklighetens geometri exakt (pool-kvintiler, fynd-takt, frågetyp från embeddings). Gymmet, ledgern, bänken och baslinjerna är nu på plats och frysta; det som saknas är träningsdata i rätt form.

## 15. Träningsdataset: riktiga erfarenheter i rätt gränssnitt

Granskningens tre slutsatser är antagna och implementerade:

1. **Sluta träna på syntetiska tiers.** Datasetets steg bär den fullständiga verkliga observationen (`pool_scanned`, `found`, `recent_hit_rate_bp`, `spent_milli`, `remaining_milli`) — exakt det gränssnitt budgetförvaltaren ser vid exekvering. Framtida träning konsumerar samma form.
2. **Samla riktiga erfarenheter — med motfaktum-förbehållet.** En inspelad körning visar vad som hände, inte vad som hade hänt under ett annat val. Datasetet är erfarenhetsdata (demonstrationer, offline-RL-indata) — aldrig en simulator. Detta står i `dataset.rs`-dokumentationen och gäller all användning.
3. **Läraren först.** Den adaptiva pipelinen är lärarpolicyn; dess beslut spelas in som demonstrationsdata, den syntetiskt tränade learens verkliga misstag spelas in som märkta negativa exempel, och terminalkvaliteten märker varje trajektoria. Kombinationen imitation + utforskning i kontrollerad miljö följer sedan.

**Datasetet (`benchmarks/real_trajectories_v1.json`, fruset):** 45 trajektorior (5 frågor × 3 budgetar × 3 policys). Varje steg innehåller observationen beslutet fattades på, handlingen, faktisk kostnad och steg-belöning; varje trajektoria slutar med verifierad kvalitet och total kostnad. Facit finns på exakt ett ställe: `terminal_quality`. Pinnade policysummor (15 trajektorior var): pipeline +882 693, equal-split +368 000, syntetisk learner −318 000. Testat: förlustfri round-trip, deterministisk replay (samma terminalkvalitet), och frys-pins (`tests/dataset_tests.rs`).

**Frågeberoende budgetering (nästa steg i designen):** SWE:s embeddings och likhets-problemlösning ska mata budgetförvaltarens initialtillstånd — en billig frågeklassificering (embedding-kluster) som första state-feature, därefter styr observerat framsteg fortsättningen. Datasetets schema bär redan `qtype` och per-stegs-observationer; embedding-baserad typning är en ny kolumn, inte en ny arkitektur.

**Automatisk generering av Golden Questions — svaret på diskussionsfrågan:** ja, med en hård varning. Mekaniskt går det: generera mallfrågor över Overgraph-dokument ("Vad säger avtalet om X?" per klausultyp), låt SWE köra research, och använd svaren som facit. Men om facit kommer från samma motor som utför researschen mäter bänken självkonsistens, inte researchkvalitet — ett cirkulärt facit är värdelöst och strider mot cratens non-negotiable 1. Den försvarbara vägen är halvautomatisk med oberoende signaler: (a) utöka det manuella guldet modest (10–30 klausulfrågor — billigt att annotera), (b) generera kandidatfrågor + kandidatevidens från strukturerad korpusdata (klausulrubriker, korsdokument-överensstämmelse där samma faktum styrks av flera oberoende dokument), (c) verifiera facit offline med JEV/LLM och behåll bara högtroende poster, (d) mänsklig stickprovsgranskning som grind. Tusentals frågor är målet; varje steg dit måste hålla facit oberoende av researche-pipelinen.

## 16. Lärare–elev-POC: leave-one-question-out-grinden

Granskningens POC-plan, genomförd i minsta kontrollerade form:

1. **Lärarpolicy** = den adaptiva pipelinen — omskriven till att vara **observations-deterministisk** (en ren funktion av gränssnittet, ingen dold minnesräknare). Mätning tvingade fram detta: en minnesbaserad lärare producerade etikettkonflikter — samma observation mappade till olika handlingar — vilket gör beteendekloning principiellt omöjlig. Gränssnittet kompletterades också med `zero_hit_streak` (facit-fri stall-räknare) och `pool_extension_yielded` (har senaste pool-utökningen betalat sig) — "osäkerhet kring om fortsatt investering kan förbättra svaret", operationaliserat.
2. **Beteendekloning** = multinomial logistisk regression (30 parametrar, SGD, ingen ny beroende) över 11 facit-fria features → lärarens tre handlingar {Invest(A,1000), Invest(B,5000), Finish}.
3. **Kontrollerad utforskning** — planerad, ej byggd: ska läggas ovanpå eleven först när grinden passerat.
4. **Oberoende utvärdering** — leave-one-question-out: träna på fyra frågor, testa på den femte, fem gånger; testfrågans alla nio trajektorior hålls utanför.

**Grinden: PASS — 1.000 överensstämmelse på alla fem foldar**, inklusive folden som håller ut den enda frågan av typ 0 (ren extrapolering till osedd typ). Roll-out-verifikation: eleven driver RealEnv på den hållna frågan och når identiskt netto som läraren vid alla tre budgetar. Tester: `tests/student_tests.rs` (3 st, pinnade), rapport: `cargo run --example v2_student`.

**Vad grinden betyder och inte betyder:** eleven kan överföra lärarens beteende till en osedd fråga — nödvändig grund för fortsatt RL. Den bevisar inte att eleven kan *överträffa* läraren; det kräver kontrollerad utforskning med terminalkvalitet som kreditsignal — och där är kreditfördelningsproblemet granskningen pekade ut: terminalkvaliteten märker episoden, inte det enskilda beslutet. Nästa steg: ε-utforskning kring lärarpolicyn i RealEnv, hårda kostnadstak, och utvärdering mot nya frågor när sådana finns (fem frågor räcker inte för generaliseringsslutsatser — §15:s dataset-väg).

## 17. Kontrollerad exploration: kan eleven överträffa läraren?

Experimentet granskningen begärde, med riktad (inte uniform) exploration, fryst utvärdering, per-beslut-avvikelser och kvalitet/kostnad åtskilda. Två diagnoser först:

1. **Tak-proben:** en handbyggd "svans-optimerad" policy (finare JEV-insatser vid stall) ger exakt lärarens netto på alla fem frågorna — det finns inget svans-slöseri att hämta (settle-bokföringen tar redan faktisk kostnad, och tröskelsvepet 6–18 visade att stall-tröskeln är betydelselös här).
2. **Elevens vokabulär utökades till sex klasser** ({A 1000, A 5000, B 1000, B 5000, B 10000, Finish}) — eleven måste kunna *uttrycka* en förbättring, inte bara imitera.

**Uppmätt (leave-one-question-out, fryst utvärdering, pinnat i `tests/explore_tests.rs`):**

| Fold (hållen fråga) | Lärare | B – enkel ε | C – riktad |
|---|---|---|---|
| auto-renewal | 64 000 (q .85) | 58 000 (q .85) — regression | 64 000 |
| notice-period | 48 231 (q .69) | **58 000 (q 1.00) — VINST +9.8k** | 48 231 |
| liability-cap | 29 000 (q .50) | **34 765 (q .62) — VINST +5.8k** | 29 000 |
| confidentiality | 79 000 (q 1.00) | 63 000 (q 1.00) — regression | 79 000 |
| liability-secrecy-carveout | 79 000 (q 1.00) | 79 000 | 79 000 |

**Acceptanskriteriet (slå läraren på ≥1 osedd fråga utan försämrad täckning): PASS — 2/5, via B.** Vinstmekanismen är avläsbar i avvikelseloggen: ε-eleven är *mer tålmodig* än läraren på frågor där likhetsordningen har fynd-gap — lärarens stall-regel avslutar för tidigt, eleven fortsätter verifiera och hittar de sista fynden (kvalitet 0.69→1.00 respektive 0.50→0.62). Kostnaden syns i de två regressionerna: samma tålmodighet kostar 6–16k på frågor där läraren redan slutat rätt.

**Två lärdomar, båda pinnade:**

1. **Den riktade explorationens prior var felriktad.** Den utforskade "billigare/avsluta"-rörelser — exakt de rörelser tak-proben visade har noll utrymme. Vinsten låg i *mer* tålmodighet vid stallgränsen, och den hittades av den enkla uniforma ε:en. Riktningen ska vara: vid stallgränsen, pröva att fortsätta — inte att sluta.
2. **Blandat utfall = det ärliga utfallet.** Eleven är inte uniformt bättre (2 vinst, 2 regression, 1 lika). Det är förväntat för en 30-parametersmodell på 5 frågor — och det är precis varför kriteriet krävde *minst en* osedd fråga, inte ett genomsnitt. Nästa steg om vi vill ha vinsterna utan regressionerna: träna direkt på avvikelserna (per-beslut-kredit via terminalkvalitet) och fler frågor — dataset-vägen i §15.

## 18. Bättre marginalnytte-observationer, läckagegranskning och djup-capture

Granskningens tre punkter, genomförda:

**1. Läckagegranskning.** Två saker. (a) Strukturellt test (`policy_selection_never_touches_held_out_outcomes`): varje fold bygger sin policy enbart av de andra fyra frågornas trajektorior — den hållna frågans id får aldrig förekomma i vare sig lärar- eller utforskningsdata; testet kör granskningen i fem foldar. (b) Process-erkännande: epokantalet justerades under mätningen med insyn i held-out-resultaten (1000 → 200); konfigurationen är nu fastslagen (ε=0.10, 20 episoder/fråga, 200 epoker, frö 7) och framtida ändringar ska pre-registreras före mätning. Inga held-out-utfall användes vid valet av *policy* — men valet av *konfiguration* var inte blindat, och det ska det vara framöver.

**2. Bättre observationer kring marginalnytta** (facit-fria, beräkningsbara ur committad data): `next_rank_bp` (nästa kandidats position i den rankade listan — proxy för likhetsförfall längre ned), `docs_remaining` (distinkta dokument kvar i poolen, från chunk-id-prefix), `docs_with_hits` (dokument med fynd hittills), `new_doc_hit` (kom senaste fyndet från ett tidigare outforskat dokument). Det är platå-vs-mättnad-signalerna granskningen bad om, i den mån fryst data bär dem — äkta likhets-poäng kräver embedding-cachen (gitignored), så rank-proxyn är det reproducerbara valet.

**Uppmätt med de nya observationerna (om-pinnat):** vinst-mönstret från §17 försvann — 0/5 foldar slår läraren, och en regression försämrar nu även kvaliteten (carveout 0.57). **Slutsatsen är metodologisk, inte negativ om idéen:** med fem frågor är vinst/regression-mönstret instabilt under byte av feature-mängd, så bänken kan inte avgöra vilka signaler som hjälper. Det är ytterligare ett bevis på att dataset-vägen (§15) är flaskhalsen — inte modellen.

**3. Djup-capture — den tredje förmågans data är nu fryst.** `cargo run --example v2_capture_deep` körde 125 live LLM-anrop (Cerebras) över de 25 bästa kandidaterna per fråga och frös `benchmarks/real_fixtures_deep/*.json`. Fyndet i datan: **alla fem frågorna har noll blind-guld** (`evidence ∩ scan_blind = ∅`) — JEV täcker redan hela facit, och LLM:s fynd är en delmängd (16/20, 11/13, 20/34, 12/13, 7/7 av guldet). Därmed har deep-förmågan **noll marginalvärde på denna bänk** — den kan inte skapa ett tre-förmåge-allokeringsspel på dessa frågor. Det är ett ärligt och viktigt bänk-fynd: för att lära SWE att förvalta en hel researchbudget krävs frågetyper där resonemang har marginalvärde (motsägelsefulla källor, syntesfrågor) — nästa steg i frågegenereringen (§15) måste prioritera just det. När sådana frågor finns är allt maskineri redo: deep-fixtures, RealEnv:s C-förmåga (maskad tills vidare) och trajektorie-insamlaren.

## 19. Research Gym: kursändring — marknaden före motorn

**RL-implementationen är frusen** (§13–§18 står som de är; inga fler hyperparameter- eller feature-ändringar mot fem-fråge-bänken). Nästa version bygger marknaden: 30 oberoende Golden Questions över tre kategorier (evidenssökning, korsdokumentanalys, resonemang/syntes) med **separat facit för nödvändig evidens och korrekt slutsats**, genererade ur verkliga dokument med en deterministisk strukturextraktor — inte av SWE:s researchmotor. Därefter mäts JEV, retrieval och LLM separat och i kombination för faktiskt marginalvärde, innan någon ytterligare RL-träning. En förmåga utan marginalvärde redovisas som sådan.

## 20. Research Gym: 30 frågor, dubbelt facit, marginalvärdesmätning

Uppdraget från kursändringen, genomfört i tre steg:

1. **Frågegeneratorn** (`tools/gen_golden_v2.py`): deterministisk strukturextraktor — klausulnyckelord + regex-värdeextraktion över de 50 riktiga avtalsdokumentens chunktexter. **Facit härleds ur dokumentstrukturen, inte ur JEV/LLM/embeddings.** 30 frågor, 10 per kategori: evidenssökning (positiva + negativa klausulfrågor), korsdokument (vilka av fyra dokument har klausulen), resonemang/syntes (uppsägningstid-värden och jämförelser). Varje fråga har **separat facit**: nödvändig evidens (chunkar) och korrekt slutsats. Allt facit är loggat med sina råa chunktexter i `benchmarks/golden_v2_verify.txt` — avsiktligt människoverifierbart, och en mänsklig granskningspass är grinden innan slutsatser litas på.
2. **Mätningen** (`examples/v2_measure.rs` + `tools/rank_candidates.py` + `tools/measure_marginal.py`): kandidat-set per fråga (24 st: facit-evidens + deterministiskt dragna distraktorer), frysta embedding-rankningar (`golden_v2_ranks.json`), och live JEV+LLM-svar frysta som fixtures (`golden_v2_fixtures/`). Analysen är offline och reproducerbar.
3. **Resultat** (720 JEV-anrop + 707 LLM-anrop, 13 ogiltiga LLM-svar = 1,8 % formatvägran — redovisas som förmåge-egenskap, inte dold):

| Plan | Täckning | Korrekthet | Kostnad (milli) |
|---|---|---|---|
| JEV ensam | 0.75 | 0.60 | 7 790 000 |
| LLM ensam | 0.73 | 0.60 | 7 790 000 |
| Retrieval+JEV | 0.75 | 0.60 | 7 790 000 |
| Retrieval+JEV+LLM | 0.78 | 0.60 | 7 790 000 |

Per kategori (kombinationen): evidenssökning 0.95 täckning / 0.90 korrekthet · korsdokument 0.90 / 0.40 · resonemang/syntes 0.50 / 0.50.

**Det ärliga svaret — och det viktigaste fyndet:** på dessa 30 frågor har **JEV och LLM nästan identiskt marginalvärde** — ingen förmåga bidrar med något unikt, och kombinationen lägger +0.03 täckning och noll korrekthet. Marknaden är fortfarande inte differentierad. Varför: frågornas slutsatser är strukturellt extraherbara (klausulnyckelord + regex), så "resonemang/syntes"-frågorna testar fortfarande hämtning, inte resonemang — och per-chunk-klassificeringen är samma uppgift för båda modellerna. Slutsatsen är metodologisk: nästa frågegenerering måste producera slutsatser som **inte** kan assembleras från nyckelordsträffar — riktig syntes (riskallokering, konsekvensbedömning, motsägelsehantering) — annars mäter bänken återigen bara retrieval. Vi konstruerar inte facit så att LLM vinner; vi bygger verkliga problem och låter resultaten visa när förmågorna skiljer sig. Korsdokumentens 0.40 visar också att den deterministiska assemblern är för strikt (exakt dokumentmängd) — en toleransfråga, inte ett förmågefel.

**Metodnot:** retrieval mäts som rankningskvalitet (frysta embeddings) — den besvarar inga frågor själv, den ordnar kandidaterna. Kostnadsmodell: JEV 1 coin/anrop, LLM 10 coins/anrop, retrieval = amorterad indexkostnad (rapporteras som embedding-tokens).

## 21. Kedje-experimentet: förändrar en förmåga värdet av en annan?

Granskningens invändning var korrekt: lika slutresultat ≠ lika marginalvärde — det sekventiella värdet (JEV:s fynd som indata till LLM-syntes) var omätt. Fem korsdokument-/syntesfrågor (g2-15, g2-17, g2-29, g2-20, g2-23), fyra kedjor per fråga, samma budget (240 coins, faktisk kostnad mäts):

| Kedja | Kostnad (medel) | Täckning | Korrekthet |
|---|---|---|---|
| JEV → deterministisk assembler | 24 000 | 0.44 | 0.40 |
| LLM → assembler | 234 000 | 0.39 | 0.40 |
| JEV → LLM-syntes | 34 000 | 0.44 | 0.20 |
| LLM → JEV → LLM | 21 600 | 0.22 | 0.20 |

Per fråga är skillnaderna lärorika: g2-15 vinner bara LLM-klassificeringen (full täckning, 240k — JEV missar ett dokument); g2-17 och g2-29 vinner JEV+assemblern (24k, korrekt) medan LLM-syntesen tappar dokument; **g2-20/g2-23 (jämförelsefrågorna) misslyckas alla kedjor med täckning 0.00** — per-chunk-klassificeringen hittar inte evidenschunkarna alls.

**Utslaget på granskningens beslutsträd: kedjorna skiljer sig inte i kvalitet på dessa frågor.** Där de skiljer sig ligger skillnaden i klassificeringssteget (JEV vs LLM per chunk), inte i syntessteget — LLM-syntesen slår aldrig den deterministiska assemblern givet samma evidens. Begränsningsanalysen, i ordning:

1. **Frågorna:** jämförelsefrågornas totala kollaps (0.00) visar att per-chunk-prompten ("besvarar denna chunk frågan?") är fel primitiv för syntesfrågor — evidenschunkarna besvarar inte frågan var för sig. Frågegenereringen måste antingen rama klassificeringen som evidensrelevans eller byta hämtningsprimitive för syntesfrågor.
2. **Syntesförmågan:** givet korrekt evidens var LLM-syntesen komplett på 1 av 3 korsdokumentfrågor — sämre än nyckelordsassemblern. Promptingen är naiv (ingen strukturerad utdata, ingen reasoning_effort) — synteskvalitet är en riktig spak som inte är mätt vid sitt bästa.
3. **Utvärderingen:** strikt mängdlikhet straffar nära-missar (2 av 3 dokument = fel); partiell kredit skulle visa gradskillnader.

**Slutsatsen:** marknaden är fortfarande inte differentierad, men nu vet vi exakt var differentieringen måste uppstå: i frågor där per-chunk-hämtning är fel primitiv och syntesen är det enda steget som kan svara — riskallokering, konsekvenser, motsägelser. Där skulle en billig JEV-undersökning + dyr LLM-syntes bli det genuina sekventiella budgetproblemet. Nästa frågegenerering prioriterar just de frågetyperna, med klassificeringsprompten omramad till evidensrelevans.

## 22. Tre kedjor, orakel-test och separata signaler

Granskningens experiment, genomfört: statisk (JEV → syntes), iterativ (JEV → gap-analys → retrieval → JEV → syntes) och adaptiv (budgetstyrd regel över samma primitiver), plus **orakel-testet** (LLM får allt facit-evidens direkt) som skiljer syntes- från upptäcktsflaskhalsen. Separata signaler: informationsvärde (upptäckte gap-steget nytt facit-evidens?), täckningsdelta och slutlig korrekthet.

**Uppmätt (5 frågor):**

| Fråga | Initial täckning | Info-värde | Orakel-syntes | Statisk | Iterativ | Adaptiv |
|---|---|---|---|---|---|---|
| g2-15 | 0.86 | 0 | ✗ | ✗ | ✗ | ✗ |
| g2-17 | 0.62 | 0 | ✓ | ✓ | ✓ | ✓ |
| g2-29 | 0.71 | 0 | ✗ | ✗ | ✗ | ✗ |
| g2-20 | 0.00 | 0 | ✓ | ✗ | ✗ | ✗ |
| g2-23 | 0.00 | 0 | ✗ | ✗ | ✗ | ✗ |

**De två viktigaste fynden:**

1. **Orakel-testet bryter isär flaskhalsarna per fråga.** g2-17 fungerar ända igenom (enda frågan där allt stämmer); g2-20 har syntesen intakt (orakel ✓) men upptäckten kollapsar (0.00) — *upptäcktsflaskhals*; g2-15/g2-29/g2-23 har syntesen som bindande begränsning (orakel ✗ trots komplett evidens) — *syntesflaskhals*. Det är exakt den diagnos granskningen bad om: vi vet nu per fråga om nästa investering ska gå till bättre hämtning eller bättre syntes.
2. **Iterativa kedjans informationsvärde = 0 på alla fem.** Mekanismen fungerar — gap-analysen identifierar riktiga saknade delar (g2-15: "Avtal_11_Distansarbetsavtal sekretessklausul", precis det JEV missat), retrieval hämtar, JEV verifierar ett nytt fynd — men det nya fyndet var aldrig facit-evidens. Kedjorna *påverkar* nu varandra (gap-analysen omdefinierar sökuppgiften), men frågorna belönar det ännu inte: facit-gapen är antingen redan täckta eller bortom per-chunk-klassificeringen.

**Slutsatsen:** tre kedjor skiljer sig inte på dessa fem frågor — men nu vet vi *varför per fråga*, och det är ett framsteg i diagnostik snarare än i marknad: syntesen är den dominerande flaskhalsen (3/5), upptäckten nästa (1/5). Fem frågor är stark diagnostik, inte grund för policyval (granskningens reservation kvarstår). Nästa steg behöver inte bara svårare frågor — det behöver frågor där gap-analysens informationsvärde kan bli > 0, dvs. där facit kräver evidens bortom första klassificeringsrundan.

