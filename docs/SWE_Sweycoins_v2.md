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
| heuristisk adaptiv | 49 062 |
| **mc-q-learner** | **128 500** |
| orakel | 132 500 |

Kalibreringsgrinden: orakel / bästa baslinje = 1.39 (krav ≥ 1.10) ✓ · learen 97 % av orakel ✓ · kriterier 1–4, 6, 7 gröna i CI-tester. Kriterium 5 (verklig bänk) kvarstår — steg 6, utvärdering mot de frysta verkliga frågorna.

## 12. Punkter i specen att justera före implementation

1. **§5.2 Action-redundans:** `INVEST`/`CONTINUE`/`START` → en `INVEST`; `TRANSFER` skjuts upp till efter POC (kredittilldelning över transfers är en egen fälla).
2. **§6 Gles belöning som default:** delbelöningar som A/B-knapp, inte grundutförande — v1:s shaping-fälla (84–210/500 → 325/500 med episodisk kredit) är dokumenterad i `docs/SWE_Sweycoins_resultat.md`.
3. **§7 Algoritmordning:** PPO/actor-critic som jämförelsearm efter kalibreringsgrinden, inte som utgångspunkt — v1 visade att enkla skikt vinner när signalen är svag.
4. **§9 POC A-arm:** A bör vara v1:s tvåfasscanner (arm H) — retrieval-ordningen stod för nästan hela vinsten på den verkliga bänken; det är den realistiska retrievalstrategin.
5. **§4 Kostnadstabell:** kalibrera mot uppmätt förbrukning i v1:s fixtures istället för platshållarvärden; indexets capital accounting finns redan (78 coins engångskostnad).
6. **§10 Modellmarknad:** rätt att hålla utanför POC; notera att ledgerns `transfer`/`reward`-konton redan är byggstenen för virtuella portföljer när den fasen kommer.
