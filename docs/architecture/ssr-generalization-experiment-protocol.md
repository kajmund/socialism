# SSR-generaliseringsprojektet — fryst experimentprotokoll v1

Status: **FRYST före resultatgenerering.** Ändringar kräver en ny version av denna fil och
dokumenterad motivering (spec §11). Komplement till [ssr-generalization-inventory.md](ssr-generalization-inventory.md).
Version: 1. Datum för frysning: 2026-10-27.

## 1. Omfattning och experimentarmar

### 1.1 Dokumentklassificering med SSR-fingeravtryck (Fas 2, offline)

Klasser: `anstallningsavtal`, `aktieagaravtal`, `ovriga_avtal` (hårda negativa).

Armar (minst, spec §5.2):
1. `metadata-free majority` — sanity baseline (alltid den vanligaste klassen bland de två kända).
2. `centroid` — diagnostisk baseline: medelvärde av alla TextUnit-embeddings per dokument (förväntas kollapsa; inkluderas för att mäta R5-risken).
3. `ssr-fingerprint` — kategorinycklade features (§2.2) + enkel linjär/regelbaserad klassificerare utan ny dependency.
4. `nearest-prototype` (valfri) — tolkningsbar baseline: närmaste klassprototyp i fingerprintrymd.

Klassificeraren ska kunna abstain vid låg högsta klass-score eller låg margin, och när för många nödvändiga kategorier saknar användbart AnchorSet.

### 1.2 Adaptiva policyexperiment i Research Gym (Fas 3, isolerat i `crates/swe-gym`)

**Policyfamilj A — escalation och modellrouting** (spec §8.1). Två separata beslutspunkter med egna policy-id:n, actionrum, rewards och versionshistorik:

- `A1 ssr_to_jev`: actions `accept_localized_candidate` (endast ren lokalisering + kvalitetsgrindar), `abstain`, `escalate` → `call_jev`. Contextfeatures: SSR top score, margin, negative signal, independent support, abstain reason, kandidatantal, source diversity, uppgiftstyp.
- `A2 model_profile`: actions `route_fast`, `route_balanced`, `route_deep`. Contextfeatures: Jev task scores (`expert_reasoning`-ekvivalenter i gymmet), krav på tools/structured/vision/long context, uppgiftstyp, hittillsvarande latency/kostnad/escalation i episoden, versioner. `call_structured_extractor` maskeras ut tills ett lokaliserat source span finns (capability-maskering).

Kontrollarmar (frysta jämförelser): nuvarande deterministiska fast/balanced/deep-router (som gym-baseline), `always-balanced`, befintlig Jev/LLM-väg utan SSR-gate, diagnostisk oracle (endast offline-gold, aldrig contender).

**Policyfamilj B — budgetallokering** (spec §8.2, helt separat från A):
- Ett budgetbeslut per episod (contextual bandit först; sekventiell RL endast om bandit-baselinen är otillräcklig och flera beroende budgetbeslut behövs). Fördelar Sweycoins mellan retrieval/SSR-, Jev- och LLM-grenar under hårt totalt tak. Återanvänder `ledger.rs` `allocate/reserve/spend/release/transfer`. Får inte avgöra semantisk correctness och får inte skapa budget genom rewards.

## 2. Frysta konstanter och definitioner

| Konstant | Värde | Motivering |
| --- | --- | --- |
| Seed nya experiment | `20261027` | Fryst här; befintliga benchar behåller sina pinnade seeds |
| Tariffer (gym) | scan 1000, deep 10000 milli Sweycoin; totalbudget 2 000 000 (bench_real_v2) | Befintlig fryst bench |
| Embedding-identitet | `text-embedding-3-large`, revision `v1`, dimension 3072 (knowledge-katalog) | Befintlig config; spec §3.3 |
| Belöningsformel (träning) | `reward = quality_gate_pass − λ_cost·normalized_cost − λ_latency·normalized_latency − severe_penalty·unsupported_or_ungrounded_output` | Spec §8.3 |
| λ_cost | `1e-7` per milli Sweycoin (normaliserad mot totalbudget) | Fryst före validering |
| λ_latency | `1/900 000` per ms (normaliserad mot SWE-timeout 1800 s) | Fryst före validering |
| severe_penalty | `1.0` (episodnivå) vid unsupported/ungrounded output | Spec §8.3 |
| Fingerprint top-m-pooling | `m = 4`, `m = 8` (båda rapporteras; m är versionerat) | Spec §5.1 |
| Stödtröskel (support_threshold) | 0,45 (match-profile-v1, arvd från dagens konstant) | Oförändrad tills benchmark visar annat |
| MIN_SIMILARITY / MIN_MARGIN | 0,25 / 0,04 (match-profile-v1) | Oförändrade tills benchmark visar annat |
| Recall-tröskel för "säker träff" (SSR→Jev-gate, gym) | top similarity ≥ 0,45 och margin ≥ 0,10 | Fryst; kalibreras i protokoll-v2 först efter data |

**Träningsreward är inte promotionsmått.** Promotion beslutas på separata mätetal (§4). Quality, kostnad, latens, abstention och deep-call-rate rapporteras alltid separat.

## 3. Data, split och leakage-kontroller

- **Klausullokalisering:** `experiments/overgraph_ingest/retrieval_gold/` (fryst legal-questions-v1, 9 klausulgolder). Gold-TextUnit-id:n hålls utanför AnchorSet-selektion. Stabilitet mäts vid 2/4/8/12 verifierade ankare per polaritet (deterministisk `deterministic_diversity`).
- **Dokumenttyp:** nytt goldenset i `experiments/ssr_fingerprint/gold/` med manifest (familj-id, org-id, klass, versionshash). Split per dokumentfamilj + organisation; near-duplicate-grind: Jaccard > 0,5 på TextUnit-hash-mängder → samma sida. Holdout 10–20 % av familjerna, orört till slutlig evaluation. Filnamn/metadata aldrig features.
- **Routing:** offline `bench_real_v2` (5 frågor) + `golden_v2` (30 frågor) för träning/validering; nya benchversioner `bench_policy_a_v1.json` / `bench_policy_b_v1.json` bredvid befintliga (befintliga filer orörda). Bred routing: `synthetic_sme` 200 GQ stratifierat per `area`; facit (`ground_truth/facit.json`) aldrig i policykontexten.
- **Order:** gold/replay först → bounded live-shadow sist. Minst 200 oberoende goldenevents innan valideringskörning; ≥ 1000 shadowbeslut före produktionsbeslut (spec §11.18).

## 4. Mätetal (rapporteras alltid separat)

- **SSR-lokalisering:** Recall@1/5/10, Precision@1/5, MRR/NDCG, scans-until-covered, first relevant rank, hard-negative ranks, false positives per kategori, selective accuracy/recall vs abstention-coverage, fel per abstain-reason, stabilitet per ankartal, shared vs tenant-specifika set.
- **Dokumentfingeravtryck:** macro-F1, balanced accuracy, P/R/F1 per klass, confusion inkl. `other/unknown`, selective accuracy vs coverage, template-/familje-held-out, ablation per feature, jämförelse mot centroid, stabilitet över dokument-/AnchorSet-versioner.
- **Värdeextraktion (Fas 4):** exakt raw-span grounding, schema validity, exact/normaliserad match per typ, unit/date/currency-normalisering, abstention precision, unsupported/hallucinerad rate.
- **Routing/RL:** golden quality pass rate + stage-regressioner, citation grounding, p50/p95 latens (service och end-to-end), token-/modell-/faktisk kostnad, Sweycoins per godkänt svar, verifierad kvalitet per Sweycoin, Jev-/LLM-/deep-call-rate, escalation rate (onödig/missad), regret mot deterministisk baseline och diagnostisk oracle, 95 % bootstrap-CI totalt och per uppgiftstyp.

## 5. Acceptansgrindar (frysta)

Se inventeringsrapporten §6 (grindar 1–18). Sammanfattning av de hårda:
- Noll tenantläckor; 100 % resolvable provenance; connection-release-regression grön; inga tysta fallbacks; scripted/replay/live alltid separerade.
- Klausullokalisering Recall@5 ≥ 0,95 utan hard-negative-försämring; scans-until-covered ≥ 2× mot produktionsreplay.
- Dokumentklassificering: macro-F1 ≥ 0,90, P/R ≥ 0,85 per klass, selective accuracy ≥ 0,95 vid ≥ 0,70 coverage, och fingerprint måste **slå** centroid (oavgjort räcker inte).
- Routing: nedre 95 % KI ≤ 1 p.e. sämre än deterministisk kontroll; SSR→Jev −30 % Jev-anrop utan > 1 p.e. kvalitetstapp; profilpolicy −20 % p95-latens eller kostnad vid samma kvalitet; budgetpolicy +10 % kvalitet/Sweycoin med ≤ 2 p.e. solve/pass-rate-tapp; ≥ 200 goldenevents + ≥ 1000 shadowbeslut före promotion.
- Extraktion (Fas 4): grounding/schema 100 %, normaliserad accuracy ≥ 0,90 (≥ 0,85 per typ), hallucinationer 0.

**Om någon grind faller: produktionen förblir oförändrad; experimentet stannar som experiment eller tas bort.**

## 6. Körningsregler

1. Ingen produktionskoppling i Fas 1–4 (ingen swe_bridge/fast gate/evidence sufficiency/routerändring).
2. Shadowloggar ändrar aldrig svar, EvidenceSet, AnchorSet eller Tabular Review-celler.
3. `PolicyDecisionEvent` (dataset v5 i gymmet) innehåller: event-/trace-/run-/attempt-id, policy family/version, context schema version, data/benchversion + seed, tillgängliga actions, vald action, **propensity**, baseline + shadow action, provider/model/profile, Jev-/embedding-/AnchorSet-/fingerprint-/classifierversioner, quality outcome + verifieringssätt, input/output tokens, service- och end-to-end-latens, faktisk kostnad + Sweycoin-kostnad, authoritative/shadow/replay/live-marker, felkategori. **Ingen rå dokumenttext, prompt eller användarmeddelande.**
4. IPS/SNIPS eller doubly robust krävs för counterfactual påståenden om icke körda actions; annars presenteras de inte.
5. Alla scriptade resultat märks `not_live_model_quality`; inga scriptade siffror beskrivs som modellkvalitet.
