# Inventering: befintliga faktapar- och konfliktmekanismer (A2/A3)

Research-ticket: [Inventera befintliga faktapar- och konfliktmekanismer](../issues/01-inventera-faktapar-och-konfliktmekanismer.md).
Fryst utgångspunkt enligt kartan: `main` (PR #422), PR #426 orörd, `b5bb4b71`.
Inventeringen är gjord mot källkoden i denna working tree; inga produktions- eller
live-anrop har gjorts i denna ticket. Alla siffror nedan är hämtade från committade
artefakter eller från repo-guider som själva redovisar körningen; inga nya mätningar
har producerats.

Läsanvisning: `fil:rad` avser working tree. "Mätt" betyder att en faktisk
modellkörning finns dokumenterad med modell och siffror. "Ej mätt" betyder att
koden finns men ingen körning är dokumenterad.

---

## 1. Vad som finns

### 1.1 Jev-experiment för passagefönster och explicita faktapar

| Komponent | Path:line | Vad den gör | Återanvändbar? |
| --- | --- | --- | --- |
| `Passage` + `split` | `backend/tests/research_reuse/jev_windows.py:15-51` | Delar ett `AssessableEvidence` i fasta teckenfönster (default 1200), med 160 tecken kontext före/efter. Kärnan täcker texten exakt; att passagerna rekonstruerar originaltexten verifieras och kastar fel annars (`:49-50`). | Ja, som laboratoriets passagevy. Inte produktionschunkning. |
| `request` | `jev_windows.py:54-66` | Bygger en `ScreenRequest` med `state={"objective", "evidence": rows}` och två frågor per passage (`relevant_to_question`, `directly_supports_answer`). Varje fråga binds till `passage_id`. | Ja. |
| `plan` | `jev_windows.py:69-87` | Batchar passager under explicit `max_state_chars` och max 16 frågor; kastar fel om en enskild passage inte ryms (`:83-84`). Ingen tyst kapning. | Ja, budgetmönstret. |
| `aggregate` / `joint` | `jev_windows.py:90-104` | Behåller båda bedömningarna från *samma* bästa passage; blandar aldrig relevans från en passage med stöd från en annan (`joint` = min av tröskel-normaliserade värden). | Ja, "samma passage"-regeln. |
| `contradiction_requests` | `jev_windows.py:107-117` | Det befintliga explicita faktaparet: exakt två `AssessableEvidence`, två anrop (en per riktning). State = `{"objective", "evidence": <ena posten>, "other_supplied_facts": [<andra posten>]}`. Frågan är `EVIDENCE_SCREEN_QUESTIONS["contradicts_current_evidence"]`. Båda påståendena skickas alltså **komplett** i båda riktningarna. | Ja, som prototyp för A3:s par-anrop. Kräver exakt två poster (`:108-109`). |
| `ScreenRequest` + `measure` | `backend/tests/research_reuse/jev_passages.py:17-21`, `:74-131` | Kör anrop med semafor, journal per anrop (`request_sha256`, `request_chars`, `question_count`, status, resolved model, latens, usage). Kastar om svars-IDs inte matchar bindings (`:99-100`) och om resolved model byter under körningen (`:125-127`). | Ja. Detta är den mest återanvändbara mät- och proveniensmekanismen. |
| `pair_control` | `backend/tests/research_reuse/jev_window_live.py:49-60` | Kör `contradiction_requests`, kontrollerar budget innan anrop och mäter. Variantnamn `separate_contradiction`. | Ja. |
| `variant` | `jev_window_live.py:13-46` | Kör `compact_rank`, `excerpt_windows` eller `source_windows`; sparar `coverage` per passage med `passage_id`, fält, start/end, käll-SHA, kontextstart/slut och `content_hash`. | Ja, täckningsposten per passage. |
| `snapshots` (passagekontroller) | `backend/tests/research_reuse/jev_controls.py:10-47` | Fem syntetiska fall: `late-court-decision`, `title-only`, `party-argument-only`, `mixed-targets`, `conflicting-dates` (positivt kontrollpar, båda förväntas `contradicts_current_evidence=True`, `:28-34`). | Ja. |
| `snapshots` (par- och fönsterkontroller) | `backend/tests/research_reuse/jev_window_controls.py:8-45` | Lägger till `late-third-window` och de tre negativa paren: `matching-dates` (identiska datum), `historical-change` (2025 ersatt av 2026), `different-contracts` (TEST-1 vs TEST-2). Alla tre förväntar `contradicts_current_evidence=False` (`:43`). `conflicting-dates` får `kind="pair"` (`:10`). | Ja. Nio kontrollfall totalt. |
| `finish` | `backend/scripts/check_jev_windows.py:68-84` | Jämför poäng mot `expected` med tröskel 0.5; sparar `checks` och `passage_checks`. | Ja, acceptanslogiken. |
| Live-runner | `backend/scripts/check_jev_windows.py:10-65` | `--controls-only`, `--repeat`, `--variants`, `--retry-429`; väljer `pair_control` när `snapshot["kind"] == "pair"` (`:48-54`); skriver aldrig över befintlig rapport (`:99-100`). | Ja. |

Viktigt: `contradiction_requests` finns bara i test-/laboratoriekoden. Den importeras
av `jev_window_live.py` och `test_jev_windows.py`, inte av någon produktionsmodul
(`grep` över `backend/app` ger inga träffar). Den är alltså ett mönster att återanvända,
inte en produktionsmekanism.

Enhetstesterna verifierar faktaparet utan nätverk:
`test_contradiction_control_compares_both_complete_facts_in_both_directions`
(`backend/tests/research_reuse/test_jev_windows.py:65-72`) och budgetfelet
`test_pair_budget_failure_prevents_external_calls_without_clipping` (`:90-97`).
Testerna bevisar formen, inte modellkvalitet.

### 1.2 Produktionens Jev-screening och routing

| Komponent | Path:line | Vad den gör | Återanvändbar? |
| --- | --- | --- | --- |
| `EVIDENCE_SCREEN_QUESTIONS` | `backend/app/services/research/evidence_screen.py:43-92` | Sex NOUL-frågor per passage: relevans, direkt stöd, `contradicts_current_evidence` (`:60-67`), `material_new_information`, `likely_duplicate_or_redundant` (`:76-83`), auktoritet. `contradicts_current_evidence` frågar "Does this evidence contradict other supplied facts?" men produktionens state innehåller **inga** `other_supplied_facts` (se 4.3). | Ja, frågetexterna. |
| `EvidenceJevScores` | `evidence_screen.py:95-106` | Tar emot alla sex poäng + latens. | Ja. |
| `EvidenceScreenCache` | `evidence_screen.py:129-150` | Per-Attempt cache, max 256 poster, nyckel = (modell, frågeuppsättningens hash, `content_hash`, normaliserad objective). | Ja, men bara inom samma Attempt/objective. |
| `screen_evidence` | `evidence_screen.py:235-259` | Screenar alla poster concurrent (semafor `research_jev_concurrency`), utelämnar felande poster. | Ja. |
| `order_evidence_for_state` | `evidence_screen.py:262-281` | Använder `likely_duplicate_or_redundant` **endast som rangordning**: `usefulness = relevant + support + new − duplicate`. Ingen bortfiltrering. | Ja, som rangordning. |
| `ASSESSMENT_QUESTIONS` | `backend/app/services/research/fast_controller.py:105-131` | Fem NOUL-frågor för route: `answerable_now`, `material_gap`, `contradiction` (`:116-120`), `follow_up_change`, `additional_source`. `contradiction` frågar om källorna motsäger varandra "on the question". | Ja. |
| `classify_research_decision` | `fast_controller.py:324-351` | Tre utfall: `sufficient` / `insufficient` / `uncertain`. `contradiction` är en av fem riskfrågor; `risk_ceiling = 1.0 − sufficient_threshold` (`:336`). Standard: sufficient 0.9, incomplete 0.85, confidence 0.8 (`backend/app/config.py:200-202`, `:333-335` i anropet). `contradiction > 0.10` blockerar `sufficient`. | Ja. |
| `ResearchJevDecision` | `backend/app/observability/research.py:18` | Literal `"sufficient"` / `"insufficient"` / `"uncertain"` / `"error"`. `error` är ett fjärde värde som `classify_research_decision` aldrig returnerar; det sätts av felvägen (`fast_controller.py:354-387`). | Ja, som enum-underlag. |
| Konsumenter | `fast_controller.py:273`; `backend/app/swe/providers.py:53`; `backend/app/services/research/sufficiency_experiment/route.py:108` | Produktionens fast gate, SWE-providern (måste matcha workflowets deklarerade `choices`, annars fel `:63-67`) och experimentets route använder samma funktion. | Ja. |
| `compact_research_state` | `backend/app/services/research/fast_state.py:33-82` | Klipper till `max_evidence_items` och shrinkar till `max_state_chars`; sätter `input_truncated` (`:68`) men payloaden innehåller **inte** vilka evidens-ID:n som föll bort. `known_contradictions` skickas som en lista av strängar (`:54`), inte som poster. | Ja med invändning: trunkeringsflaggan är explicit, listan över utelämnade ID:n är det inte. |

Route-semantik som är relevant för A2:

- `map_jev_outcome` (`sufficiency_experiment/route.py:29-42`) mappar både `sufficient`
  och `insufficient` till `FINISH`; bara `uncertain` kan nå `ESCALATE_NARRATIVE`, och
  då endast om quality-gaten redan förbjuder `sufficient`.
- `_emit_status` (`sufficiency_experiment/loop.py:264-276`) sätter `sufficient` från
  quality + aggregations utan att läsa route-resultatet. Detta är samma lager-3-fynd
  som trace-guiden beskriver (`docs/guides/evidence-sufficiency-contradiction-trace.md:92-101`).
- `route_state` (`route.py:139-172`) skickar bara en sammanfattning av
  obligationsstatus, `unresolved_conflicts` och `span_coverage` — ingen evidens- eller
  passage-text. Det förklarar varför route-svaren är identiska för olika fall (se M11 i avsnitt 2).

### 1.3 Sufficiency-experimentet (DB-fritt)

Paketet är opt-in och importeras inte av produktionsassessorn
(`backend/app/services/research/sufficiency_experiment/__init__.py:1`).
Det har **ingen** DB-, OverGraph- eller embeddings-koppling: en `grep` över paketet
finner bara strängen `"session"` i `tools.py:30` (förbjuden verktygslista). Körningen
är `WorkflowRunner` med rena dataklasser. Live-körning kräver ändå en Jev-klient och
nätverk; helt offline är paketet bara med `ScriptedSufficiencyJev` (`scripted.py:18-90`).

| Komponent | Path:line | Vad den gör | Återanvändbar? |
| --- | --- | --- | --- |
| `segment_text` / `segment_evidence` | `sufficiency_experiment/segment.py:24-66` | Semantisk delning vid paragraf/mening/mellanslag, max 1500 tecken; `_assert_full_cover` kastar om varje källtecken inte täcks (`:80-90`). | Ja, täckningsgarantin. |
| `evaluate_job` | `sufficiency_experiment/jev_eval.py:71-133` | Ett anrop per (need, passage). State = `need_id`, `question`, `passage_id`, `evidence_id`, `passage` (`:80-86`) — **ingen** annan evidens. Vid fel sätts alla poäng till 0.0 och `error` sätts (`:110-123`); paret får alltså inte "låg motsägelse" av ett teknikfel. `independence_key` beräknas från `QualityEvidenceInput` (`:124`). | Ja, men notera att motsägelsefrågan ställs utan jämförelsepost. |
| `aggregate_need` | `sufficiency_experiment/aggregate.py:19-75` | Bygger `ObligationState` per obligation; `factual_support` kräver `min_independent_sources` distinkta `independence_key` (`:116-129`); `completeness` kräver source type (`:130-132`). | Ja. |
| `_contradictions` | `aggregate.py:143-151` | `contradicts_current_evidence >= config.contradict_threshold` (0.6) → passage-ID i `contradictions` och `contradicting_passage_ids`. | Ja, tröskelregeln. |
| `_status` / `unresolved_conflicts` | `aggregate.py:51-75`, `:154-159` | Olösta konflikter ⇒ `uncertain`, aldrig `insufficient`; konflikten bevaras. | Ja. |
| `quality_gate` | `sufficiency_experiment/quality.py:15-71` | `span_coverage < 1.0`, `omitted_evidence_ids`, `missing_evaluations`, `evaluation_errors`, `budget_exhausted`, `unknown_requirements`, `unresolved_conflicts`, `obligations_unverified` blockerar `allows_sufficient` (`:20-42`). `resolve_conflict` blir ett tillåtet subworkflow bara om `unresolved_conflicts` finns och `subworkflow_rounds < 2` (`:46-50`). | Ja. |
| `route_state` / `resolve_conflict` | `sufficiency_experiment/route.py:139-203` | `resolve_conflict` markerar en konflikt "adresserad" bara om **alla** motstridande passager har `likely_duplicate_or_redundant >= config.support_threshold` (`:185-203`). Ingen majoritetsröstning, ingen borttagning. | Ja, men se luckan i 4.2. |
| `draft_from_aggregations` | `sufficiency_experiment/emit.py:17-49` | Skriver `contradictions` som **passage-ID:n** in i `ResearchNeedAssessment.contradictions` och `ResearchAssessmentDraft.contradictions`; ingen konfliktpost med påståenden/regel/konfidens. | Delvis. |
| `ExperimentReport` | `sufficiency_experiment/types.py:155-177` | `coverage = judged_chars / source_chars` (`:173-177`). Innehåller `evaluations`, `aggregations`, `quality`, `route`, `jev_calls`, `llm_calls`, `failure_mode`, `live_measurement`. | Ja. |
| `case_trace` | `sufficiency_experiment/trace.py:23-51` | Per passage: text endast om den bär `signal`, fem NOUL-poäng, `contradiction_flagged`, `signal_present`; per fall: aggregations, quality, `route_state`, route, draft. | Ja, spårformatet. |
| `ScriptedSufficiencyJev` | `sufficiency_experiment/scripted.py:18-90` | Stänger av modellen: `CONTRADICTION_SIGNAL` i texten ⇒ `contradicts_current_evidence=0.95`; `likely_duplicate_or_redundant` är **alltid** `0.05` (`:54-68`). | Endast som CI-dubbel. Kan inte öva duplicate-baserad konfliktlösning. |
| `ExperimentConfig` | `sufficiency_experiment/types.py:32-47` | `max_passage_chars=1500`, `support_threshold=0.6`, `contradict_threshold=0.6`, `max_jev_calls=2000`, `max_subworkflow_rounds=2`, `max_narrative_depth=1`, `max_narrative_input_chars=12000`. | Ja. |
| `run_narrative` | `sufficiency_experiment/narrative.py:32-62` | Skickar aggregations (passage-ID:n, inte text); kastar `ValueError` om payloaden överstiger `max_narrative_input_chars` (`:52-54`). | Ja, fail-loud-budgeten. |
| Verktygsallowlist | `sufficiency_experiment/tools.py:15-36` | Endast fem typade workflows; `search`, `database`, `sql`, `session`, `http`, `spawn_agent` är förbjudna. | Ja, A3:s subworkflow-gräns. |
| SWE-definition | `sufficiency_experiment/workflow.py:29-107` | `task` → `decision(expression)` → `map` → `aggregate` → `route` → `decision` → `resolve`/`narrative` → `emit`; `map` är den enda parallelliteten (`:49-55`). | Ja, A3 kan följa samma nodtyper. |

### 1.4 Persistenta fakta, TextUnits och claims

| Komponent | Path:line | Vad den gör | Status |
| --- | --- | --- | --- |
| `GraphFact` | `backend/app/database/graph_v2.py:47-76` | SQL-modell med `identity_key`, `source_id`/`target_id`/`context_id`, `predicate`, `fact_text`, `normalized_text`, `embedding`, `valid_at`/`invalid_at`, `status`. | **Död tabell.** `alembic/versions/192_drop_graph_tables.py:33-46` droppar `graph_facts` (och `graph_fact_sources`, `graph_fact_relations`, `graph_fact_question_dependencies`). Modellen finns kvar men kan inte läsas i en migrerad DB. |
| `GraphFactSource` | `graph_v2.py:79-90` | Faktans källor (`source_kind`, `source_ref`). | Död tabell (samma migration). |
| `GraphFactRelation` | `graph_v2.py:93-100` | `from_fact_id` → `predicate` → `to_fact_id`. | Död tabell. Se konflikt om kantlabel i 4.1. |
| `GraphFactView` | `backend/app/services/overgraph/model.py:44-61` | Research-vyn: `id` (= OverGraph-nyckel), scope, source/target, `predicate`, `fact_text`, `status`, `valid_at`/`invalid_at`, `attributes`, `text_unit_refs`, `created_at`. | **Levande.** Byggs av `fact_view` (`overgraph/views.py:40-61`) från en `GraphRecord`. |
| `TextUnitView` / `TextUnitWrite` | `model.py:20-41`, `:64-81` | Kanonisk passage med dokument/version, `text`, `content_hash`, `ordinal`, sektion, sid-/teckenintervall, giltighetstid, embedding, `next_id`. | Levande. |
| `KnowledgeHit` | `model.py:84-92` | Sökträff: `kind` ∈ {fact, text_unit, entity}, score, scope, text, props, hop. | Levande. |
| TextUnit skriv/läs | `backend/app/services/overgraph/text_units.py:23-83` (skriv), `:86-123` (läs per version/ett ID) | Skriver TextUnit + `DocumentVersion`-ankare + `CONTAINS`; läser tillbaka i dokumentordning. | Levande. |
| Faktaläsning i praktiken (OverGraph) | `require_knowledge()` i `backend/app/services/overgraph/catalogs.py:423-426`; runtime öppnas från `overgraph_dir` (`backend/app/config.py:134`, default `data/overgraph`) | OverGraph är processägd lokal katalog. Utan öppen runtime kastar läsningen `RuntimeError`. | Kan öppnas offline mot en temp-katalog; testfixturen gör det (`backend/tests/conftest.py:127-136`). |
| Claim-identitet | `backend/app/services/knowledge/identity.py:67-76` | `sha256(scope_key + predicate + kanonisk JSON av normaliserat värde)`. Volatila fält (bl.a. `excerpt`, `wording`, `question`, `quote`, `timestamp`) tas bort före hash (`:10-38`, `:52-64`). | Levande och återanvändbar. |
| `KnowledgeClaim` | `backend/app/services/knowledge/claims.py:58-75` | `id`, `predicate`, `value` (dict), `supporting_text_unit_ids`, scope, `persistence_class`, `observation_kind`. **Inga** explicita fält för giltighetstid, kontext eller dokumentversion. | Levande. |
| Claim-läsning i grafen | `backend/app/services/overgraph/legal_claims.py:84` (`claim_in_graph`), `:299` (`supporting_text_units`) | Slår upp claim på identitet respektive dess `SUPPORTS`-TextUnits. | Levande, kräver OverGraph-runtime. |
| Claim-persistens | `backend/app/services/knowledge/claim_store.py:37-105` | Kräver `supporting_text_unit_ids` (annars fel `:56-57`), validerar identiteten (`:67-73`), skriver till grafen och en `CLAIM_ADDED`-händelse. | Levande, men skrivvägen kräver `AsyncSession` (för grafhändelsen) och en öppen OverGraph-runtime. |

Två **olika** identitetsbegrepp samexisterar:

1. **Claim-identitet** = scope + predicate + normaliserat påstående. Samma påstående från
   två källor blir **en** claim-nod; proveniens är TextUnits (`knowledge/claims.py:1-6`).
2. **Fact-identitet** = källankrad: `source_fact_identity(... document_version_id,
   source_unit_key, fact_occurrence_key)` (`backend/app/services/overgraph/write.py:216-240`).
   Identisk formulering i två källförekomster blir **två** faktanoder.

Detta är en faktisk klyvning som A3 måste förhålla sig till, inte en implementationsdetalj.

### 1.5 Konfliktskrivning i grafen

| Komponent | Path:line | Vad den gör | Status |
| --- | --- | --- | --- |
| `CONTRADICTS`-label | `backend/app/services/overgraph/labels.py:22` | Kantlabel i OverGraph. | Finns. |
| `write_fact(..., contradiction_key=...)` | `backend/app/services/overgraph/write.py:320-352` | Skriver faktanoden och, om `contradiction_key` anges, en `CONTRADICTS`-kant mellan fakta (ordnade engine-ID:n, `:347-351`). | **Ingen anropare.** `grep` över `backend/app` visar bara definitionen. Ingen detektering producerar någon `contradiction_key`. |
| `JevFactJudge.compare` | `backend/app/services/graph_v2/jev_judge.py:11-27` | Jev choice-fråga över `{"proposed_fact", "existing_fact"}` med utfallen `SAME` / `DISTINCT` / `CONTRADICTS`; ogiltigt svar kastar `JevMalformedResponseError` (`:25-26`). | **Endast testad**, ingen produktionsanropare (`grep` ger bara `backend/tests/test_graph_v2_jev_judge.py`). |
| Prompttexten | `backend/app/services/graph_v2/prompts.py:8-31` | "Choose SAME only if both assert the same proposition, CONTRADICTS only if they cannot both be true at the same valid time... A contradiction does not itself revoke a prior fact." | Finns som promptfält `research.graph_fact_resolution` / `rattsunderlag.graph_fact_resolution`. |
| `resolve_fact` | `backend/app/services/overgraph/ingest.py:17-35` | Skriver source-anchored faktum; `judge` och `embedder` tas emot men **används inte**; docstring säger att semantiska relationer är "a separate workflow over already stored facts" (`:24-30`). | Bekräftar att faktaparsdetektering inte är inkopplad. |
| `KnowledgeRelationship` + mirror | `backend/app/services/knowledge/relationships.py:179-217`; `backend/app/services/knowledge/graph_relationship_mirror.py:58-88` | Kan skriva en `CONTRADICTS`-kant mellan claim/entity/text_unit/document med `extra`-properties; kräver att båda ändpunkterna finns i grafen (`relationships.py:190-194`). | Levande, men ingen konfliktstatus, ingen regel och ingen lösningsproveniens i schemat. |
| `graph_fact_relations` i paritetskontrollen | `backend/app/services/knowledge/verify_graph_parity.py:258-270` | Kontrollerar att varje SQL-rad har en **`LINKED`**-kant i grafen. | Oförenligt med `docs/architecture-review/01-sql-layer.md:610` som säger `CONTRADICTS` för samma tabell. Se 4.1. |

### 1.6 Kandidatgenerering och embeddings

| Komponent | Path:line | Vad den gör | Kostnad/konfiguration |
| --- | --- | --- | --- |
| `hybrid_fact_hits` | `backend/app/services/overgraph/hybrid_retrieval.py:131-165` | Reciprocal-rank fusion (`RRF_K=50`, `:22-23`) av lexikala Tantivy-träffar och densa OverGraph-träffar; kandidatbudget `max(100, limit*5)` (`:145`). | Kräver `Catalog` + byggt `TextUnitIndex`; ingen modellkostnad utöver query-embedding. |
| `ensure_fact_index_current` | `hybrid_retrieval.py:45-54` | Kastar `FactIndexStaleError` om indexet ligger efter grafen. | Skyddar mot tyst ofullständig lexikal sökning. |
| `lookup_candidates` | `backend/app/services/overgraph/research.py:375-394` | Kör `collect_research_hits` i katalogen: `question_facts` (DEPENDS_ON), `search_research_facts` (dense + TextUnit→facts), `neighbourhood_facts` (SUBJECT/OBJECT via entiteter). | Kräver öppen OverGraph-runtime. |
| `question_frontier` | `research.py:337-372` | Deterministisk traversal från fråge/nod-startpunkter, filtrerar på `predicate`, returnerar fakta-poster med source/target. | Ingen modellkostnad. Närmast en befintlig "samma entitet/predikat"-väg. |
| `search_research_facts` | `research.py:115-136` | Dense `hybrid_search` + expansion via TextUnits. | Query-embedding. |
| `graph_reuse.lookup_graph_evidence` | `backend/app/services/research/graph_reuse.py:30-90` | Produktionens enda research-läsväg för persisterad kunskap. Kräver `customer_id` (`:40-44`), `AsyncSession`, query-embedding (`:105-117`) och `graph_has_supported_facts` (`:106-107`). | DB-session + OverGraph + OpenAI-embedding. |
| Embedding-provider | `backend/app/services/knowledge/embeddings.py:154-211` | OpenAI `text-embedding-3-large`, batch ≤ 2048 (`:16`, `:175`), in-process cache 2048 poster (`:17`, `:62-104`), `OPENAI_API_KEY` krävs (`:204-206`). | `backend/app/config.py:102-106`: modell `text-embedding-3-large`, dimension 3072, timeout 60 s, bas-URL OpenAI. |
| Retrieval-gräns | `backend/app/config.py:214` | `research_knowledge_lookup_limit=10` (1–32). | Antal faktakandidater per need. |
| Täckningsbarhet | `backend/app/config.py:134` | `overgraph_dir="data/overgraph"` (gitignored; katalogen finns lokalt i denna tree). | Lokal katalog, ingen Postgres. |

Ingen befintlig funktion grupperar fakta på *gemensam entitet/attribut och olika värde*.
`fact_key` (`write.py:216-240`) och `question_frontier` (predikat + SUBJECT/OBJECT) är
byggstenarna, men ingen "hitta par med samma källa/mål/predikat och olika `fact_text`"
finns.

### 1.7 Oberoende, dubbletter och kvalitet

| Komponent | Path:line | Vad den gör | Användning |
| --- | --- | --- | --- |
| `QualityEvidenceInput` | `backend/app/services/research/quality.py:81-101` | Den vy kvalitetsscorern får se: item/evidence-ID, need, source_type, status, titel, excerpt, locator, source_id/url, provider, provenance, retrieved_at, content_hash. | Kvalitetsbarriären. |
| `independence_key` | `quality.py:194-207` | Stabil underliggande källidentitet i prioritetsordning: `source_id` → `source_url` → `provider+locator` → `content_hash` → `item_id`. Kanoniserar URL: fragment tas bort, host lower, query behålls, trailing slash tas bort (`:264-276`). | Ja. Kopior av samma källa kolliderar. |
| `_found_independence_counts` | `quality.py:402-412` | Räknar distinkta källor per `research_need_id` bland `status == "found"` och poster som inte är `provenance["derived"]`. | Ja. |
| `assess_evidence_quality` | `quality.py:415-498` | Sätter `independence_key` och `independent_source_count` per post. | Ja. |
| `group_evidence_for_review` | `backend/app/services/research/assessment.py:124-156` | Grupperar på `source_id` eller `source_url` eller `content:<hash>` + sorterade need-ID:n + status + `content_hash`; övriga ID:n blir `duplicate_evidence_ids` (`:152-156`). | Ja, exakta dubbletter. |
| `likely_duplicate_or_redundant` | `evidence_screen.py:76-83` | LLM-bedömning av "restates the same source or fact". | Används som rangordning (`:262-281`) och som konfliktlösningsregel (`route.py:185-203`). **Inte** som identitet eller filter i produktion. |
| `resolve_conflict` | `sufficiency_experiment/route.py:175-203` | En konflikt får anses adresserad endast om varje motstridande passage har duplicate-score ≥ 0.6. | Ja, men se 4.2. |
| `aggregate._state` | `sufficiency_experiment/aggregate.py:107-140` | `factual_support` verifieras av antalet distinkta `independence_key` bland passager med relevans ≥ 0.6 och stöd ≥ 0.6. | Ja. |
| `obligations_for_need` | `sufficiency_experiment/obligations.py:15-42` | `min_independent_sources=2` om `"corroboration" in need.capabilities`, annars 1. | Ja. |

De två begreppen är **inte kopplade**: en hög LLM-duplicate-score ändrar aldrig
`independence_key`-grupperingen, och `independence_key` påverkar aldrig
`resolve_conflict`. Trace-guiden visar att det är precis den klyftan som gör att en
upptäckt konflikt kan avfärdas som dubblett (`docs/guides/evidence-sufficiency-contradiction-trace.md:70-90`).

### 1.8 Budgetar, trunkering och explicit utelämning

| Mekanism | Path:line | Beteende |
| --- | --- | --- |
| `ASSESSMENT_MAX_INPUT_CHARS` | `backend/app/services/research/assessment_input.py:12` | 60 000 tecken för produktionsassessorns input. |
| `ASSESSMENT_PASSAGE_CHARS` | `assessment_input.py:13` | 1 500 tecken per passage; längre klipps med markören `…[trunkerad]` (`:202-205`). |
| `encode_assessment_input` | `assessment_input.py:229-300` | Först full payload med `budget` + `omitted_evidence: []`; om den inte ryms trunkeras rader och hela poster väljs bort en i taget. Varje bortvald post får `reason: "assessment_char_budget"`, och `budget` redovisar `included_evidence`/`omitted_evidence` (`:268-297`). Om inget ryms kastas `ResearchAssessmentError` (`:298-299`). |
| `AssessmentInput.omitted_evidence_ids` | `assessment_input.py:132-136` | Följer med ut till anroparen. |
| `jev_state_char_budget` | `backend/app/config.py:59` (8000, 256–32 000) | **Används inte av research-Jev.** Bara av LLM-auto-routing (`backend/app/llm/selection.py:389`) och answer-review-klassificering (`backend/app/services/knowledge/answer_review_classification.py:53`). Research-Jev styrs av `research_jev_max_state_chars` (se nästa rad). |
| `research_jev_max_state_chars` | `config.py:204` | 6 000 tecken (256–32 000) för research-Jev. Tillsammans med `research_jev_max_evidence_items=24` (`:203`), `research_jev_concurrency=8` (`:205`), `research_jev_timeout_seconds=5.0` (`:206`), `research_jev_enabled=False` (`:197`), `research_jev_mode="shadow"` (`:198`). |
| `compact_research_state` | `backend/app/services/research/fast_state.py:33-82` | Klipper/shrinkar; `input_truncated` sätts (`:68`). `research_jev_max_state_chars` överskrids aldrig; om hela passagen inte ryms kastas fel i laboratoriekoden (`jev_windows.py:83-84`). |
| `ExperimentConfig`-budgetar | `sufficiency_experiment/types.py:32-47` | `max_passage_chars=1500`, `max_jev_calls=2000`, `max_narrative_input_chars=12000`, `max_narrative_depth=1`, `max_subworkflow_rounds=2`. |
| Narrativ budget | `sufficiency_experiment/narrative.py:52-54` | Överskriden budget ⇒ `ValueError`, ingen kapning. |
| Deterministisk precheck-selection (dokumenterad, ej implementerad i denna tree) | `docs/architecture/evidence-sufficiency-narrative-precheck.md:288-318` | Prioritetsordning: bas → Jev-flaggade motsägelser → boundary sample → Jev-flaggat stöd → spread; `omitted`-schema med `passage_id`, `content_hash`, `reason`; vägrar hellre än att utelämna en flaggad motsägelse. |
| Täckningspost per passage | `backend/tests/research_reuse/jev_window_live.py:30-35` | `coverage[]` med `passage_id`, fält, start/end, käll-SHA, kontext, `content_hash`. |

Det finns alltså tre nivåer av utelämning i repo: (a) `assessment_input` redovisar
bortvalda poster med orsak, (b) `compact_research_state` sätter en trunkeringsflagga
men inte vilka poster som föll bort, (c) laboratoriets passageplan kastar fel istället
för att klippa. Någon gemensam "omitted"-posttyp finns inte.

### 1.9 Golden cases och mätartefakter

| Artefakt | Path:line | Innehåll |
| --- | --- | --- |
| Golden cases (11) | `backend/app/services/research/sufficiency_experiment/golden.py:29-42` | `short_sufficient`, `no_support`, `tail_counterevidence`, `late_evidence`, `large_567k`, `multi_obligation`, `missing_source_type`, `unknown_requirements`, `duplicate_sources`, `later_wave_contradiction`, `adversarial_empty`. |
| Signaler | `golden.py:11-16` | `SUPPORT_PHRASE`, `CONTRADICTION_SIGNAL` ("MOTBEVIS: detta avgörande tillämpar inte 36 § avtalslagen."), `IRRELEVANT`, `LARGE_FILLER`, `TAIL_FILLER`. |
| Fyra benchmarkfall | `golden.py:45-52` | `tail_counterevidence`, `late_evidence`, `large_567k`, `short_sufficient`. |
| `duplicate_sources` | `golden.py:196-224` | Fem kopior med samma `source_id`; `capabilities=["corroboration"]` kräver 2 oberoende källor. |
| `later_wave_contradiction` | `golden.py:227-242` | Stöd i våg 1, motsägelse i våg 2 (`provenance={"wave": 2}`). Aggregeringen läser inte `provenance["wave"]`. |
| Live-artefakt | `backend/tests/integration/baselines/sufficiency-experiment-live-v1.json` | 4 fall, `measurement="live"`, `model={jev: jev-1.13.0, llm_provider: cerebras, llm_calls_total: 0}`, summary + per-fall. |
| Trace-artefakt | `backend/tests/integration/baselines/sufficiency-contradiction-trace-v1.json` | 4 fall med full `trace` per passage; `trace.config.jev_model="jev-latest"`, trösklar 0.6/0.6, 1500 tecken, 2000 anrop. |
| PR #420-fixture | `backend/tests/fixtures/sufficiency_experiment/pr420_cerebras_baseline.json` | Publicerad mätning: 567 673 → 56 443 tecken, Cerebras `gpt-oss-120b`, output cap 8 192 tokens. |
| Mät- och trace-scripts | `backend/scripts/benchmark_evidence_sufficiency.py:32`; `backend/scripts/trace_evidence_sufficiency.py:62-64` | Kör `measure_live_models(...)`; trace-scriptet sätter `include_trace=True`. |

Övriga baselines i `backend/tests/integration/baselines/` är dokument-/kanal-/expertmätningar
och innehåller inga faktapar- eller konfliktmätningar.

---

## 2. Tidigare live-mätningar av motsägelse- och faktaparbeteende

Alla rader nedan är faktiska modellkörningar om inte raden säger annat.

| # | Vad som mättes | Modell (begärd → resolved) | Siffror | Källa |
| --- | --- | --- | --- | --- |
| M1 | Explicit faktapar: 4 parfall × 2 riktningar × 2 iterationer (härlett ur kontrollistan och `--repeat 2`) | `openjev-latest` → `openjev-0.1` | **16/16 riktade kontroller korrekta**; negativt svar för `different-contracts` låg nära tröskeln **0,477 mot 0,5** | `docs/guides/research-reuse-tests.md:690-698` |
| M2 | Passagekontroller (stöd), samma körning | `openjev-0.1` | Båda passagevarianterna klarade **12/12 märkta svarsstödskontroller per variant**; korta varianten missade de två sena domsluten i båda iterationerna; 12 passagepoäng från tredje fönstret granskades och gav rätt passage | `docs/guides/research-reuse-tests.md:690-695` |
| M3 | Enkelpostsscreening av uttrycklig datumkonflikt | `openjev-0.1` | Endast den **andra** posten flaggades, i båda iterationerna; enskilda anrop saknar jämförelsepost | `docs/guides/research-reuse-tests.md:568-576` |
| M4 | Screeningvarianter (`compact` vs `batched_refs`) på hela det frysta underlaget (79 poster → 77 granskningsgrupper), samtidighet 8 | `openjev-0.1` | `compact`: 9,28 s / 77 anrop / 47 132 indatatokens; `batched_refs`: 17,07 s / 39 anrop / 285 847 tokens | `docs/guides/research-reuse-tests.md:550-560` |
| M5 | Passagevarianter, samtidighet 1 | `openjev-0.1` | Kort utdrag: 61,18 s / 77 anrop / 35 582 tokens. Utdragspassager: 59,35 s / 70 anrop / 194 passager / 192 306 kärntecken / 191 944 tokens. Råtextspassager: 125,97 s / 141 anrop / 349 passager / 376 838 tecken / 369 178 tokens. Upprepning: utdrag 58,68 s; korta varianten time-outade | `docs/guides/research-reuse-tests.md:668-680` |
| M6 | Samma varianter, samtidighet 8 | `openjev-0.1` | Kort variant 9,44 s; passagevarianten avbröts av HTTP 429 efter 51 lyckade anrop; isolerat prov av enbart utdragspassager 9,15 s / 70 anrop | `docs/guides/research-reuse-tests.md:682-688` |
| M7 | Backoff-experiment | `openjev-0.1` | 294 logiska anrop lyckades efter 316 HTTP-försök; 20 anrop behövde omförsök, 2 fick 429 två gånger, max 3 försök; 22 svar var 429 med `Retry-After: 5` och "60 requests per minute per key" | `docs/guides/research-reuse-tests.md:704-726` |
| M8 | Sufficiency-experimentets 4 golden cases, komplett EvidenceSet | Jev `jev-1.13.0`; 0 LLM-anrop | Accuracy 0,25 (baseline) mot **0,5** (experiment); false-sufficient 1,0 mot **0,667**; täckning 0,299 mot **1,0**; latens 3,85 ms mot 17 978,79 ms; kostnad 0 Jev/4 LLM/119 240 tecken mot **1 043 Jev**/0 LLM/**1 478 044 tecken** | `backend/tests/integration/baselines/sufficiency-experiment-live-v1.json` (`summary`); metrics-definitioner i `docs/guides/evidence-sufficiency-experiment.md:52-61` |
| M9 | Per fall i M8 | `jev-1.13.0` | `tail_counterevidence`: sufficient (falskt), 55 anrop, 80 122 tecken, 2 725 ms. `late_evidence`: sufficient (falskt), 589 anrop, 836 514 tecken, 41 496 ms. `large_567k`: insufficient/uncertain (rätt), 397 anrop, 561 346 tecken, 27 218 ms. `short_sufficient`: sufficient (rätt), 2 anrop, 62 tecken, 476 ms | samma JSON, `cases[].experiment` |
| M10 | Motsägelsepoäng i trace, två live-körningar 2026-10-22 | `jev-latest` → `jev-1.13.0` | `contradicts_current_evidence` **0,19–0,26** mot tröskel 0,6; ingen passage nådde 0,4. Per fall (körning 1/2): 0,19/0,22; 0,26/0,25; 0,26/0,26; 0,05/0,05. Verdicts reproducerades; signalpoäng inom ±0,03 | `docs/guides/evidence-sufficiency-contradiction-trace.md:24-40`, `:134-142`; artefakten `sufficiency-contradiction-trace-v1.json` |
| M11 | Route-svar för tre fall med identiskt route-state | `jev-1.13.0` | `answerable_now` 0,94, `contradiction` 0,04, `confidence` 0,89 — identiska för `tail_counterevidence`, `late_evidence`, `short_sufficient` | `docs/guides/evidence-sufficiency-contradiction-trace.md:63-68` |
| M12 | Kontrafaktisk replay av duplicate-tröskeln (inte en ny live-körning) | — | Med signalens motsägelsepoäng satt till 0,95: `tail` körning 1 duplicate 0,57 ⇒ uncertain/insufficient; körning 2 duplicate 0,61 ⇒ **sufficient**; `late` 0,89 ⇒ **sufficient**. Marginal 0,04 runt 0,6 | `docs/guides/evidence-sufficiency-contradiction-trace.md:70-90` |

### Vad som är mätt respektive inte mätt

**Mätt live**

- Att Jev kan bedöma ett **explicit givet** faktapar i båda riktningarna (M1).
- Att enskilda passageanrop inte kan upptäcka en motsägelse som ligger i en annan post
  (M3, M10, M11).
- Att en duplicate-score kan avfärda en konflikt i `resolve_conflict` (M12).
- Att komplett passagebedömning ger hög täckning men hög kostnad (M8, M9).
- Att **experimentloopens** route-svar inte styr `sufficient`-utfallet (M11 + `_emit_status`). Det gäller experimentet; produktionsshortcuten i `fast_gate` styrs däremot av Jev-beslutet.

**Ej mätt**

- Automatisk upptäckt av relevanta faktapar. Guiden säger uttryckligen att experimentet
  "upptäcker inte automatiskt alla relevanta faktapar i de verkliga 77 posterna"
  (`docs/guides/research-reuse-tests.md:621-626`).
- `JevFactJudge.compare` i produktion eller live; bara enhetstestad
  (`backend/tests/test_graph_v2_jev_judge.py`).
- `write_fact(contradiction_key=...)` och OverGraph `CONTRADICTS`-kanter för fakta:
  ingen anropare, ingen artefakt.
- Produktionens `contradicts_current_evidence` som beslutsunderlag: poängen beräknas
  och emitteras (`evidence_screen.py:352-389`) men konsumeras inte av någon gate.
- Claim-extraktion, claim coverage och conflict-candidate coverage (A3): inga mätningar
  eller artefakter finns.
- Ett andra domarperspektiv för faktapar. Trace-guiden anger att en andra domare vore
  en separat mätning (`docs/guides/evidence-sufficiency-contradiction-trace.md:134-142`).
- De tre negativa parens enskilda poäng utöver `different-contracts` 0,477; guiden
  redovisar bara aggregatet 16/16.

---

## 3. Reuse-vs-new: utkastmatris för A2/A3

Detta är en **inventering**, inte ett designbeslut. "New" betyder att ingen befintlig
motsvarighet hittades, inte att en ny abstraktion föreslås.

| Mekanism | Befintlig motsvarighet | Reuse / Extend / New | Motivering (faktaunderlag) |
| --- | --- | --- | --- |
| **Dubblett vs oberoende** | `quality.independence_key` (`quality.py:194-207`), `_found_independence_counts` (`:402-412`), `independent_source_count` (`EvidenceQualityDraft`, `:151-152`), `group_evidence_for_review` (`assessment.py:124-156`), `likely_duplicate_or_redundant` (`evidence_screen.py:76-83`), `resolve_conflict` (`route.py:175-203`), `aggregate._state` (`aggregate.py:107-140`) | **Reuse** för källidentitet och exakta kopior. **Extend** för att koppla LLM-duplicate till identitet. **New** endast om A2 kräver ett kanoniskt `duplicate`-omdöme som skiljer sig från både `independence_key` och duplicate-score. | Två oberoende begrepp finns redan: deterministisk källidentitet och LLM-score. Ingen kod kopplar dem; `resolve_conflict` låter en duplicate-score ≥ 0,6 lösa en konflikt (`route.py:185-203`), medan `independence_key` aldrig påverkas av scoren. M12 visar att gränsen 0,6 är skör (0,57 vs 0,61). |
| **Konfliktpost (conflict record)** | `NeedAggregation.contradictions` / `unresolved_conflicts` (`types.py:96-107`), `ObligationState.contradicting_passage_ids` / `addressed` (`:86-94`), `ResearchNeedAssessment.contradictions` (`assessment.py:76-86`), `ResearchAssessmentDraft.contradictions` (`:90-107`), `QualityDecision.reasons` (`sufficiency_experiment/quality.py:20-42`), `CaseTrace.contradiction_passages` (`trace.py:42-44`), OverGraph `CONTRADICTS` + `extra` (`relationships.py:179-217`, `graph_relationship_mirror.py:58-88`) | **Reuse** för passage-ID:n och "unresolved ⇒ uncertain". **Extend** med jämförda påståenden, regel/bedömning, källunderlag och konfidens. **New** om posten ska överleva processen; ingen sådan posttyp finns. | Dagens "post" är en tuple av passage-ID:n (`aggregate.py:143-151`) som emitteras vidare (`emit.py:44`). Den innehåller varken påståenden, vald lösningsregel eller provenance. `relationships.py` kan lagra en `CONTRADICTS`-kant med `extra`, men har ingen status/regel/lösningssemantik. `graph_fact_relations` är en droppad tabell (migration 192). |
| **Claim-identitet** | `knowledge_claim_identity` (`identity.py:67-76`), `KnowledgeClaim` (`knowledge/claims.py:58-75`), `TextUnit` (`knowledge/units.py:81-93`), `GraphFactView` (`overgraph/model.py:44-61`), `source_fact_identity` (`write.py:216-240`), `knowledge_observation_id` (`identity.py:79-92`) | **Reuse** hash- och normaliseringsmekanismen samt TextUnit-ankaret. **Extend** med passage-offsets, dokumentversion, giltighetstid och kontext. **New** endast för den extractor som går från `AssessableEvidence`-text till claims; ingen sådan finns i `sufficiency_experiment`. | Claim-identiteten är påstående-baserad (samma assertion = en nod), medan fact-identiteten är källankrad (samma assertion i två källor = två noder) (`write.py:216-240`). `KnowledgeClaim` har inga explicita fält för `valid_at`/`invalid_at`/context; `GraphFactView` har det (`model.py:55-60`). A3 måste välja eller kombinera dessa, inte uppfinna en tredje. |
| **Kandidatgenerering** | `contradiction_requests` (`jev_windows.py:107-117`), `question_frontier` (`research.py:337-372`), `neighbourhood_facts` (`:138-160`), `question_facts` (`:162-181`), `hybrid_fact_hits` (`hybrid_retrieval.py:131-165`), `lookup_candidates` (`research.py:375-394`), `graph_reuse` (`graph_reuse.py:30-90`), embeddings (`knowledge/embeddings.py:154-211`; `config.py:102-106`) | **Reuse** det explicita parbygget och de deterministiska entitets-/predikatvägarna. **Extend** med ett filter "samma källa/mål/predikat (eller samma need/entitet) men olika värde". **New** för själva parurvalsalgoritmen och dess budget/provenance; ingen sådan finns. | Befintliga kandidatvägar returnerar enskilda fakta (`ResearchFactHit`) och har ingen värdejämförelse. `question_frontier` filtrerar på `predicate` men jämför inte `fact_text`. `contradiction_requests` kräver exakt två poster som redan pekats ut. Guiden säger att automatisk parupptäckt inte är gjord (`research-reuse-tests.md:621-626`). Kostnad: query-embedding (3072 dim, OpenAI) eller helt deterministisk traversal; `research_knowledge_lookup_limit=10`. |
| **Faktaparsbedömning** | `contradiction_requests` + `ScreenRequest` + `measure` (`jev_windows.py:107-117`, `jev_passages.py:74-131`), `EVIDENCE_SCREEN_QUESTIONS["contradicts_current_evidence"]` (`evidence_screen.py:60-67`), `JevFactJudge.compare` + prompt (`graph_v2/jev_judge.py:11-27`, `graph_v2/prompts.py:8-31`), `aggregate._contradictions` (`aggregate.py:143-151`), `ExperimentConfig.contradict_threshold=0.6` (`types.py:44-47`) | **Reuse** båda anropsformerna och NOUL/choice-infrastrukturen. **Extend** den binära NOUL-frågan eller den trevägs `SAME/DISTINCT/CONTRADICTS`-frågan till de fyra utfall A3 kräver. **New** för det fjärde utfallet (otillräcklig information) och för konfidensregeln; ingen befintlig fråga har fyra utfall. | Den binära frågan har två utfall (`evidence_screen.py:60-67`). `JevFactJudge` har tre (`jev_judge.py:25`). Ingen har "tillräcklig/otillräcklig information" som eget utfall. Båda skickar båda påståendena; `contradiction_requests` skickar dem i båda riktningarna (`jev_windows.py:112-116`), vilket är den enda live-mätta formen (M1). `write_fact` kan skriva en `CONTRADICTS`-kant men har ingen anropare (`write.py:320-352`). |
| **Täckningsredovisning** | `segment_text` + `_assert_full_cover` (`segment.py:24-40`, `:80-90`), `ExperimentReport.coverage` (`types.py:155-177`), `quality_gate` `span_coverage` (`quality.py:21-22`), `assessment_input` `omitted_evidence`/`budget` (`assessment_input.py:268-297`), `compact_research_state.input_truncated` (`fast_state.py:68`), `coverage[]` per passage (`jev_window_live.py:30-35`), precheck-`omitted`-schema (`docs/architecture/evidence-sufficiency-narrative-precheck.md:288-318`) | **Reuse** tecken-/passagetäckning och omissionsräknare. **Extend** med nivåerna claim coverage, conflict-candidate coverage och narrative coverage. **New** för de tre senare; `ExperimentReport` har bara `judged_chars`/`source_chars` och `quality.omitted_evidence_ids`. | Dagens coverage är en kvot tecken (`types.py:173-177`) och `quality_gate` behandlar `< 1.0` som blockering (`quality.py:21-22`). Den säger inget om claims, par eller narrativ. `ExperimentReport` saknar fält för "obehandlade par" och "möjliga men ej bedömda par". Guiden varnar uttryckligen för att förväxla passage-coverage med semantisk täckning (`docs/architecture/workflow-first-execution.md:126-128`). |

---

## 4. Luckor och öppna frågor för A2/A3-besluten

### 4.1 Oklart vilken kantlabel som är auktoritativ för faktamotsägelser

- `write_fact` skriver `CONTRADICTS` (`write.py:347-351`), men har ingen anropare.
- Paritetskontrollen för `graph_fact_relations` kräver en **`LINKED`**-kant
  (`verify_graph_parity.py:258-270`), medan `docs/architecture-review/01-sql-layer.md:610`
  säger att tabellen motsvarar en OverGraph `CONTRADICTS`-kant.
- `graph_relationship_mirror` mappar `CONTRADICTS`-relationen till `CONTRADICTS`
  (`graph_relationship_mirror.py:30`), inte `LINKED`.

Fråga till A2: vilken av dessa vägar är den avsedda för en faktapar-konflikt, och
finns det någon data som redan använder den? Inventeringen kan inte avgöra det utan
att läsa en produktionsgraf.

### 4.2 Duplicate-score och källoberoende är inte samma sak

`resolve_conflict` löser en konflikt när alla motstridande passager är
"duplicate/redundant" ≥ 0,6 (`route.py:185-203`). M12 visar att samma passage fick
0,57 respektive 0,61 i två körningar, vilket ensamt ändrade utfallet till `sufficient`.
`independence_key` (som avgör "fem kopior = en källa", `aggregate.py:116-121`) påverkas
inte av duplicate-scoren. A2 måste avgöra om dessa två ska kopplas, och i så fall hur.

### 4.3 Motsägelsefrågan ställs utan jämförelseunderlag i produktions- och experimentvägen

- Produktionens screening: state = en post, ingen `other_supplied_facts`
  (`fast_state.py:85-101`, `evidence_screen.py:60-67`).
- Sufficiency-experimentets passageanrop: state = en passage
  (`jev_eval.py:80-86`).
- Enda vägen med båda påståendena är laboratoriets `contradiction_requests`
  (`jev_windows.py:107-117`) och `JevFactJudge` (`jev_judge.py:16-27`).

A3 kan alltså inte återanvända produktions- eller experimentvägen för parbedömning
utan att bygga ett nytt anrop; däremot kan `ScreenRequest`/`measure` och
`JevFactJudge`-prompten återanvändas.

### 4.4 Ingen automatisk kandidatgenerering finns

Alla befintliga kandidatvägar returnerar enskilda fakta eller kräver att paret redan
pekats ut. Det finns ingen gruppering på gemensam entitet/attribut med olika värde,
ingen budget för par och ingen post för "möjligt par som inte kunde bedömas".
Guiden bekräftar att detta återstår (`research-reuse-tests.md:621-626`, `:700-702`).

### 4.5 Konfliktposten är inte persistent

Dagens konfliktdata är passage-ID:n i `NeedAggregation`/`ResearchAssessmentDraft`
(`types.py:96-107`, `emit.py:44`). Det finns ingen tabell, nod eller artefaktpost med
"jämförda påståenden + regel + källunderlag + konfidens + provenance". En
`CONTRADICTS`-kant med `extra` (`relationships.py:179-217`) är den enda persistenta
motsvarigheten, men saknar status och lösningssemantik. A2:s beslut om var posten ska
leva (ExperimentReport vs spårartefakt vs grafkant) är därför öppet.

### 4.6 Claim-identitet vs fact-identitet

Samma påstående från två källor blir en claim-nod (`identity.py:67-76`) men två
faktanoder (`write.py:216-240`). A3 måste välja vilket identitetsbegrepp som styr
"jämförbara claims" och hur `valid_at`/`invalid_at`/kontext representeras; `KnowledgeClaim`
har inga sådana fält (`knowledge/claims.py:58-75`), `GraphFactView` har dem
(`model.py:55-60`).

### 4.7 Täckningsnivåerna 3–5 saknar både fält och nämnare

`ExperimentReport` (`types.py:155-177`) och `QualityDecision` (`:121-130`) räcker för
nivå 2 (passage/tecken) men inte för claim coverage, conflict-candidate coverage eller
narrative coverage. Det finns inte heller någon post för "par som inte kunde bedömas
på grund av budget eller saknad kontext", vilket A3:s spårbarhetskrav efterfrågar.

### 4.8 `jev_state_char_budget` är inte research-Jev:s budget

Ticketen namnger `jev_state_char_budget`. Den används bara av LLM-auto-routing
(`llm/selection.py:389`) och answer-review (`answer_review_classification.py:53`).
Research-Jev styrs av `research_jev_max_state_chars=6000` (`config.py:204`) och
`research_jev_max_evidence_items=24` (`:203`). Ett A3-beslut som refererar
`jev_state_char_budget` riskerar att beskriva fel budget.

### 4.9 Den offline-körbara ytan

Sufficiency-experimentet är helt DB-fritt (1.3), men OverGraph-katalogen kan öppnas
mot en lokal katalog (`config.py:134`, `tests/conftest.py:127-136`). Det finns alltså
två olika "offline"-nivåer: (a) enbart `AssessableEvidence` som i dag, (b) OverGraph
lokalt utan Postgres. Ingen befintlig experimentkod gör (b), och embeddings kräver
`OPENAI_API_KEY` och nätverk (`embeddings.py:204-206`). A3 måste veta vilken nivå
mätningen ska köras på.

### 4.10 Golden cases saknar negativa parfall och duplicate-not-under-conflict-fall

De elva golden cases (`golden.py:29-42`) innehåller `duplicate_sources` och
`later_wave_contradiction`, men inget fall med *hög redundans + faktisk motsägelse*
(den kombination A2:s acceptanskriterier nämner), inget `matching-dates`/
`historical-change`/`different-contracts`-fall i sufficiency-paketet (de finns bara i
`tests/research_reuse/jev_window_controls.py:22-44`), och inget fall med
"fem kopior men två olika påståenden". Den scriptade domen kan dessutom aldrig
producera duplicate > 0,05 (`scripted.py:66`), så CI-benchmarken kan inte pröva
A2:s duplicate-regel.

### 4.11 Modell- och endpointberoende

Alla faktaparsiffror kommer från en endpoint: `openjev-0.1` (M1–M7) respektive
`jev-1.13.0` (M8–M11). Trace-guiden säger uttryckligen att detta inte är en kalibrering
och att en andra domare vore en separat mätning
(`docs/guides/evidence-sufficiency-contradiction-trace.md:134-142`). Inga mätningar
finns på Cerebras/LLM-vägen för faktapar.

---

## 5. Det jag inte kunde verifiera

- **Specens §7.2 fyra exempel**: specen finns inte i repot (endast kartan, tickets och
  de docs som kartan länkar). Jag kan därför inte bekräfta att de fyra exempel som
  A3-ticketen refererar till motsvarar de fyra kontrollparen i
  `jev_window_controls.py` eller något annat.
- **Live-resultatfil för `check_jev_windows.py`**: siffrorna i M1–M7 finns bara som
  prosa i `docs/guides/research-reuse-tests.md`; ingen JSON-rapport är committad.
  Jag har inte kört om experimentet (kräver `TYPESAFE_API_KEY`, nätverk och en sparad
  `saved-assessment-input.json` som inte finns i repot).
- **Produktionsgrafens innehåll**: jag har inte läst `backend/data/overgraph`
  (gitignored lokal katalog). Hur många `CONTRADICTS`-kanter som faktiskt finns, och
  vilken label `graph_fact_relations`-migreringen använde i praktiken, är därför
  overifierat. Katalogen finns på disk men inventeringen bygger på kod och artefakter.
- **Om `GraphFact`-modellerna kan läsas i en icke-migrerad DB**: modellerna finns kvar
  i `graph_v2.py`, men migration 192 droppar tabellerna. Jag har inte öppnat någon
  databas; slutsatsen bygger på migrationsfilen och dess docstring.
- **`prune_unsupported_claims`** (`claim_store.py:141-153`) läser
  `KnowledgeClaimRecord`/`KnowledgeClaimTextUnit`, trots att migration 192 listar
  `knowledge_claims` och `knowledge_claim_text_units` som droppade. Om den vägen
  anropas i en migrerad DB är oklart; jag har inte kunnat verifiera det utan DB.
- **Faktiska svarstider/kostnader för A3** går inte att härleda ur inventeringen;
  alla siffror ovan är från befintliga körningar med andra state-format.
