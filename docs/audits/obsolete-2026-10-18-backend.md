# Audit A — obsolet/död Python-kod i backend (app/**, scripts/**) + oanvända settings

> **Uppdatering 2026-10-18:** Flera av fynden nedan är genomförda enligt borttagningspolicyn
> (kod som bara nåddes av icke-experimentella tester). Se [syntesens §6](obsolete-2026-10-18.md#6-borttagningar-genomförda-enligt-borttagningspolicyn-2026-10-18).
> Rapporten i övrigt beskriver läget före borttagningarna.

**Repo:** `/Users/erikfremred/socialism` · **Branch:** `fix/sme-group-chat-voice` · **Auditdatum:** 2026-10-18
**Område:** endast `backend/app/**`, `backend/scripts/**`, `backend/app/config.py`/settings. DB-schema, testfall och frontend ägs av andra medlemmar.
**Läge:** läskvitto read-only. Arbetskopian är en aktiv feature-branch; filer markerade `UNTRACKED` är nya i branchen, `TRACKED` finns i git.

## 0. Omedelbar varning (farligt att ta bort / trasigt)

1. **`scripts/benchmark_prompt_configurations.py:651` — `NameError` i produktionsnära benchmark.** Ruff F821: `require_anchor_sets_for_language` är **inte importerad** i skriptet (funktionen finns i `app/services/anchor_store.py:224`; `anchor_pool.py:503` importerar den korrekt). Alla körningar med `skip_ssr=False` kraschar på denna rad. Skriptet är dokumenterat i `backend/AGENTS.md` och refereras i docs. **Fixa importen — radera inte skriptet.** (Verdict B — bugg, inte död kod.)
2. **Test-only-moduler får inte raderas utan att deras testsvit tas bort samtidigt** (se avsnitt 2). `app/services/document_qa/process_probe.py` anropas som subprocess `python -m app.services.document_qa.process_probe` från `tests/test_document_qa_multiprocess.py:15` — radering bryter testet, inte produktionen.
3. **`app/services/research/graphiti_adapter.py`** är en avsiktlig framtida adapter ("a later Neo4j driver can be plugged in") och nås bara från tester. Radera endast efter beslut om Graphiti-spåret; annars lämna (Verdict C).

## 1. Metod (reproducerbar)

- **Importgraf (AST):** `/tmp/obsolete-audit/analyze.py`, Python 3.13. Moduler = `app.*`, `scripts.*`, `alembic.*`, `tests.*` (1324 moduler). Kanter från `ast.Import`/`ast.ImportFrom` (inkl. relativ import och `as`-alias). Rotsnoder: `app/main.py`, `app/seed.py`, `alembic/env.py`, alla `scripts/*`, alla `tests/**`, alla moduler med `__main__`-guard, samt `python -m app.…`-referenser i `docs/`, `Makefile`, `.github/`.
- **Router-mountning:** alla `include_router`-anrop i hela backend jämfördes mot `app/api/*.py`; `app/api/message_images.router` monteras via `app/api/messages.py:43` (idag korrekt).
- **Referensräkning toppnivå-definitioner:** AST-räkning av `Name`/`Attribute`/import-alias i alla prod- och testfiler, **plus** ordgräns-sökning i hela repot (`.py/.md/.ts/.tsx/.yaml/.toml/.json/Makefile`, exkl. `.venv`, `node_modules`, `experiments`, `log`, `data`). Kandidater verifierades manuellt: en definition vars **enda förekomst i hela repot är definitionsraden** = A. Alias-importer (`from x import f as _f`) och kommentars-/docstring-referenser har kontrollerats separat så att de inte ger falska "döda".
- **Ej flaggat (dynamiska vägar):** FastAPI-dekoratorer/routerregistrering, SQLAlchemy-relationship-strängar, Alembic `env.py`, pytest fixtures/plugins, `importlib`/`getattr`/`__import__`, manifestfält, moduler som körs som `python -m app.…` och refereras i docs.
- **Settings:** alla fält i `Settings` (`app/config.py`, 154 st) + `LiveSpeechSettings` räknades mot `settings.<fält>` i app+scripts+alembic+tests, med separata sökningar på `self.<fält>` och repo-text. `.env.example` (151 nycklar) jämfördes mot Settings-fält (pydantic-settings är skiftlägesokänsligt; `LiveSpeechSettings` ärvs i `Settings`, `MIGRATION_DATABASE_URL` läses via `app/migration_config.py`).
- **Ruff:** `backend/.venv/bin/ruff check app scripts --select F401,F811,F841,F821 --output-format concise` → endast 2 fynd (avsnitt 6).

**Kandidatmoduler i app/ som inte nås från någon prod-rot: 7.** Moduler nådda endast från `tests/` (test-only): 7 (+1 untracked testprobe). Moduler helt onåbara från både prod och tester: **0** (tidigare "orphans" var falska positiver från paket-`__init__.py`; verifierat att alla nås via delmoduler).

## 2. Moduler som endast nås från tester (prod-död, test-beroende)

Sökning: importgraf + ordgräns i hela repot. Alla utom en är `TRACKED`.

| Fil | Vad | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| `app/services/knowledge/revalidation.py` (US: docstring rad 1) | Hela modulen: legacy claim/event-revalidering | Importgraf: ej nådd från prod-rot. Docstring: *"Legacy claim/event revalidation retained only for the cutover test suite. Production research code must not call this module."* Refereras endast från `tests/`. `docs/guides/research-durable-execution.md:129-130`: graph-revalidering är borta | **A** | Ta bort modul + dess cutover-tester (eller flytta till `tests/`-hjälp) efter att ha verifierat att migrationerna i Alembic inte importerar den. |
| `app/services/job_watch.py` (US rad 1) | `send_jobs_snapshot` — materialiserar jobbsnapshot före WS-skrivning | Enda referens: `tests/test_workspace_audit.py:216`. Produktionens `/ws/jobs` använder `app/api/workspace_job_watch.py` (`app/api/ws.py:207-215`) | **B** | Sannolikt kvarglömd äldre variant. Jämför med `workspace_job_watch`; ta bort om testet kan använda produktionsvägen. |
| `app/services/research/question_graph_memory.py` (US rad 1) | `InMemoryQuestionEvidenceGraph` | Docstring: *"In-process QuestionEvidenceGraph for tests."* Endast `tests/test_workspace_question_scope.py`, `test_workspace_expert_memory.py`, `test_iterative_knowledge_question_research.py`, `test_research_question_evidence.py` | **B** | Testdubbel — flytta till `tests/` eller acceptera som testinfra. Inte produktionsdöd i strikt mening. |
| `app/services/research/question_semantic.py` (US rad 1) | Semantisk KnowledgeQuestion-identitetsmatchning mot vektorindex | Importgraf: endast tester. **Dess settings är oanvända** (se avsnitt 3: `research_question_semantic_match_threshold/match_limit/embedding_version` läses aldrig) | **A/B** | Feature är inte inkopplad i prod. Antingen koppla in eller ta bort modul + 3 settings; idag är de död vikt. |
| `app/services/graph_v2/temporal.py` (US rad 1) | `invalidate_fact` — explicit invalidering med tidsguard | Importgraf: endast `tests/`; inga anrop i prod. AGENTS/docs säger att Graph v2:s revalideringsköer är borta | **B** | Ta bort tillsammans med ev. tester om invalidering inte ska återinföras. |
| `app/services/overgraph/traversal.py` (US rad 1) | Budgeterad traversal (Jev-scoring av kandidater) | Importgraf: endast `tests/`; importerar `research.fast_controller`/`jev` men anropas inte från prod | **B** | Kontrollera om den är tänkt för retrieval-vägen; annars bort. |
| `app/services/research/graphiti_adapter.py` (US rad 1) | Graphiti-formade node/edge-payloads bakom `QuestionEvidenceGraph` | Endast `tests/test_research_question_evidence.py`. Docstring: SDK:n är inte runtime-beroende; "a later Neo4j driver can be plugged in" | **C** | Avsiktlig framtidsseam. Radera bara efter arkitekturbeslut; annars behåll + dokumentera varför. |
| `app/services/document_qa/process_probe.py` (**UNTRACKED**, rad 1) | Tvåprocess-probe för tenant-OverGraph; "Not a production API" | Anropas endast som subprocess från `tests/test_document_qa_multiprocess.py:15` | **C** | Testinfra — behåll, men placera under `tests/`-hjälp eller dokumentera undantaget. |

Övrigt noterat (ej död): `app/services/research_eval_harness.py` (rad 1) nås endast från `scripts/evaluate_36_avtl.py`, `tests/test_research_eval_harness.py` och dokumenteras som CLI i `docs/guides/research-domain-results.md:25` → **levande**, behåll.

## 3. Oanvända settings/env-flaggor

`Settings` har 154 fält. Endast **3 fält läses aldrig någonstans** i backend (`settings.<fält>` saknas i app/scripts/alembic/tests; verifierat repo-vid ordgräns). `LiveSpeechSettings` (21 fält) har inga oanvända fält — `live_speech_vad_*` läses via `source.<fält>` i `vad_client_config` (`app/live_speech_settings.py:50-60`), så `settings.<fält>`-räkningen är en falsk positiv där.

| Fil:rad | Vad | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| `app/config.py:215` | `research_question_semantic_match_threshold` | Enda förekomsten i hela repot är definitionsraden (sökning på fältnamn i `.py/.md/.toml/.example`) | **A** | Ta bort; hör till oinkopplad `question_semantic` (avsnitt 2). |
| `app/config.py:218` | `research_question_semantic_match_limit` | Samma — endast definitionsraden | **A** | Ta bort. |
| `app/config.py:219` | `research_question_embedding_version` | Samma — endast definitionsraden | **A** | Ta bort. |
| `backend/.env.example:24-25` | `DOCUMENT_KNOWLEDGE_LLM_MAX_TOKENS`, `DOCUMENT_KNOWLEDGE_LLM_TIMEOUT_SECONDS` | Dokumenterade i `.env.example` **och** `docs/guides/backend-setup.md:31-32,106-107`, men **ingen Python-kod läser dem** (`grep -rn 'document_knowledge_llm'` → 0 träffar i app/scripts/tests) | **A** | Antingen ta bort nycklarna ur `.env.example` + docs, eller (om avsikten var per-batch-budget) implementera läsningen i dokument-Q&A-kedjan. Idag är dokumentationen vilseledande. |
| `app/config.py:143` `okf_manual_dir`; `app/config.py:234` `word_review_router_model` | Läses via `self.<fält>` i config.py (`:487`, `:483`, `:291`) | Verifierat i kontext — **inte döda** | — | Ingen åtgärd. (`word_review_router_model` har även ett default-vakttest.) |

**Env-paritet:** `LIVE_SPEECH_*` och `TTS_CACHE_*` i `.env.example` mappas korrekt via `class Settings(LiveSpeechSettings, BaseSettings)` (`app/config.py:23`) resp. `LiveSpeechSettings`; `MIGRATION_DATABASE_URL` läses av `app/migration_config.py:19` + `alembic/env.py:27`. Inga övriga saknade nycklar.

## 4. Nollrefererade toppnivå-definitioner (app/)

80 kandidater efter filtrering (publika funktioner/klasser/konstanter med 0 AST-/textreferenser). 76 av dem har verifierats repo-vid med ordgränssökning; **66 av dessa 76 förekommer exakt en gång i hela repot: definitionsraden** → bekräftat oanvända. Resterande är alias-/kommentarsreferenser eller test-only och listas som B/C. Övriga 4 kandidater (i `process_probe.py`) är test-only subprocess-hjälpare (Verdict C).

### 4a. Bekräftat oanvända (A) — endast definitionsraden i hela repot

| Fil:rad | Vad | Bevis | Verdict |
|---|---|---|---|
| `app/auth/scope.py:12` | `owner_user_id_from_job()` | Ordgräns i hela repot: 1 träff (def). Jobb-ägarskap hanteras via `job_visible_to_user`/`job_payload_visible_to_user` i samma fil | **A** |
| `app/realtime/hub.py:125` | `JobHub = EventHub` "Back-compat alias used by jobs" | 1 träff (def); ingen kod använder `JobHub` (jobben använder `job_hub = EventHub(...)` rad 127) | **A** |
| `app/schemas/kund.py:39` | `ProjektCreate` (Pydantic-modell) | 1 träff (def); inga routes/tester använder den | **A** |
| `app/services/report/charts.py:54` | `C_INK` (palettkonstant) | 1 träff (def); övriga `C_*` används | **A** |
| `app/services/persona_chat.py:67` | `ChatSuggestions` (dataclass) | 1 träff (def); följdfrågor går via `suggest_follow_up_questions` | **A** |
| `app/services/word/application.py:19,25-29` | `APPLICATION_STATUSES`, `UNRESOLVED_STALE/AMBIGUOUS/MISSING/UNCERTAIN/UNSUPPORTED` | 1 träff var (def). Övriga `APPLICATION_*` används; dessa fem är bara strängvärden som används som literals i API-svaren | **A/B** |
| `app/services/document_ingest_batch/stages.py:13,17` | `PENDING`, `SEARCHABLE_STAGES` | 1 träff var (def). `TERMINAL_STATUSES`/`FAILED_KNOWLEDGE` används | **A** |
| `app/services/document_qa/types.py:9` | `REVIEW_STATUSES` | 1 träff (def). `QUESTION_KINDS`/`ANSWER_STATUSES` används | **A** |
| `app/services/simulation/artifact/schema.py:24` | `RUNTIME_TABLES` | 1 träff (def) | **A** |
| `app/services/llm_runtime_settings.py:521` | `get_or_none()` | 1 träff (def); `load_runtime_settings` används i stället | **A** |
| `app/services/document_ingest_batch/progress.py:42` | `record_indexing()` | 1 träff (def); `record_searchable` används (`catalog_apply.py:13`) | **A** |
| `app/services/research/progress.py:364` | `deliver_research_progress_events()` | 1 träff (def); `schedule_research_progress_delivery` (`:346`) är den använda vägen | **A** |
| `app/services/research/need_normalization.py:27` | `NoOpNeedNormalizer` | 1 träff (def); `set_research_need_normalizer_factory` (`composition.py:112`) är också oanvänd | **A** |
| `app/services/research/composition.py:112` | `set_research_need_normalizer_factory()` | 1 träff (def); ingen test/prod sätter den | **A** |
| `app/services/report/bundles.py:223` | `build_bundle()` | 1 träff (def) | **A** |
| `app/services/report/locale.py:11` | `DEFAULT_LOCALE` (backend) | 1 träff i backend (def); frontend/word-addin har egna `DEFAULT_LOCALE` — backend-konstanten används inte | **A/B** |
| `app/services/report/segment_analysis.py:209` | `interview_quote_label()` | 1 träff (def) | **A** |
| `app/services/district_context.py:98` | `get_district_context()` | 1 träff (def); `area_block_for_name` i samma fil används | **A** |
| `app/services/population_generate.py:390` | `sample_politik_person_identity()` | 1 träff (def) | **A** |
| `app/services/catalog_defaults.py:296` | `SECTION_LABELS` | 1 träff (def) | **A/B** (kan vara tänkt som katalogmetadata) |
| `app/services/dd/company_mcp.py:228` | `candidates_from_company_text()` | 1 träff (def) | **A** |
| `app/services/document_find/taxonomy.py:8` (**UNTRACKED**) | `TAXONOMY_VERSION` | 1 träff (def); ingen version läses/skrivs | **A/B** |
| `app/services/stored_objects.py:258` | `list_underlag()` | 1 träff (def) | **A** |
| `app/services/word/actions.py:74` | `load_word_action()` | 1 träff (def); `load_word_actions`/`load_word_action_by_source` används | **A** |
| `app/services/ssr/embeddings.py:45` | `reset_embedding_client()` | 1 träff (def); ingen conftest använder den | **A/B** (testhygien-helper) |
| `app/llm/vision.py:44` | `reset_vision_client()` | 1 träff (def) | **A/B** |
| `app/llm/runtime_override.py:193` | `bound_llm_prompt()` | 1 träff (def) | **A** |
| `app/llm/chat.py:358` | `stream_reply_as_expert()` | 1 träff (def); expert-chatt går via `expert_consult`/`expert_reasoning_*` | **B** (dubbelkolla att ingen strängdispatch finns) |
| `app/services/knowledge/observations.py:104` | `persist_knowledge_observations()` | 1 träff (def) | **B** (kan vara tänkt persist-API) |
| `app/services/knowledge/persistence.py:55` | `get_readable_canonical_document_by_identity()` | 1 träff (def) | **B** |
| `app/services/lagen_nu/question_validation.py:84,517` | `KeepLegalQuestionValidator`, `runtime_need_from_normalized()` | 1 träff var (def) | **B** |
| `app/services/lagen_nu/selection.py:170` | `require_hit_decisions()` | 1 träff (def) | **B** |
| `app/services/lagen_nu/research_source.py:200` | `looks_like_case_citation()` | 1 träff (def) | **B** |
| `app/services/lagen_nu/text_unit_research.py:55` | `join_text_units()` | 1 träff (def) | **A** |
| `app/services/overgraph/catalogs.py:332` | `knowledge_type_for()` | 1 träff (def) | **B** (OverGraph-API kan anropas via dynamik; kontrollera `overgraph`-paketet) |
| `app/services/overgraph/ingest.py:69,73` | `ingest_entities()`, `fact_identity_key()` | 1 träff var (def) | **B** |
| `app/services/overgraph/isolation.py:17` | `assert_visible()` | 1 träff (def) | **B** |
| `app/services/overgraph/labels.py:21` | `KNOWLEDGE_TYPES` | 1 träff (def); enskilda labels används | **B** |
| `app/services/overgraph/research.py:156,411,434` | `load_fact()`, `question_seed_keys()`, `question_frontier()` | 1 träff var (def) | **B** (äldre research-API ovanpå OverGraph) |
| `app/services/research/knowledge_question.py:208,214,243` | `question_scope_from_tenant()`, `tenant_from_question_scope()`, `question_from_need()` | 1 träff var (def) | **B** |
| `app/services/research/question_iteration.py:93,269` | `empty_grounded_refs()`, `bind_need_to_question()` | 1 träff var (def) | **B** |
| `app/services/research/quality.py:255` | `hard_quality_warnings()` | 1 träff (def) | **B** |
| `app/services/expertgranskning/__init__.py:10` | `WORD_REVIEW_METHOD` | 1 träff (def) | **B** |
| `app/services/expertgranskning/observation.py:37-38` | `WORD_COMMENT_TARGET_MIN/MAX_WORDS` | 1 träff var (def) | **B** |
| `app/services/expertgranskning/schemas.py:30` | `INTENT_QUESTION_TYPES` | 1 träff i backend (def); **word-addin har egen kopia** (`src/lib/types.ts`, `src/lib/intentInterview.ts`) — backend-konstanten validerar inget | **A** (död backend-konstant) / **B** om den ska börja användas i schemavalidering |
| `app/services/expertgranskning/memory.py:29,37,38` | `MemorySource`, `MEM0_PGVECTOR_MINCONN/MAXCONN` | 1 träff var (def) | **B/C** (Mem0-konstanter kan konsumeras av Mem0-konfigurationssträngar — kontrollera innan borttagning) |
| `app/services/spindoctor_mcp_tools.py:77` | `SPINDOCTOR_MCP_TOOL_NAMES` | 1 träff (def); `allowed_spindoctor_tool_names()` används | **A/B** |
| `app/services/sme_expert_turns.py:26` | `SME_EXPERT_TURN_STATUSES` | 1 träff i backend; frontend har matchande strängar (`src/products/sme/smeTurnRecovery.ts`) | **A/B** |
| `app/services/word/tasks.py:18,19,22,23` | `SUPPORTED_WORD_SCOPE_TYPES`, `SUPPORTED_WORD_EXPERT_STRATEGY_TYPES`, `WordTaskScopeType`, `WordExpertStrategyType` | 1 träff var i backend; word-addin använder egna typer | **B** |
| `app/services/playground_tools.py:17` | `ToolFamily` | 1 träff (def) | **B** |
| `app/services/document_ingest_batch/serialize.py` / `workspace_reuse.py` m.fl. (**UNTRACKED**) | Övriga 0-referens-definitioner i untracked filer | Se `analysis.txt` avsnitt 3 | **C** (nya filer i branchen — kan vara under uppbyggnad) |

**Summering:** 80 kandidater; **66 med endast definitionsraden** (stark A-grund), varav de säkraste för direkt borttagning är tabellens A-rader ovan (~25 st). B-rader kräver att man först bekräftar att ingen dynamisk/strängbaserad användning finns (OverGraph API, Word-addin-kontrakt, Mem0).

## 5. Backend/scripts — engångs- och oanvända skript

Referensräkning: skriptets filnamn sökt i `Makefile`, `.github/`, `docs/**`, `tests/**`, `scripts/**`, `pyproject.toml`, `AGENTS.md`. `0` = ingen referens utanför skriptet självt.

| Fil | Vad | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| `scripts/demo_quick_report.py` (TRACKED) | Demo: genererar snabbrapport-HTML lokalt, "no API keys" | 0 referenser i Makefile/CI/docs/tester | **B** | Engångsdemo. Flytta till `docs/`-exempel eller ta bort; inte del av CI. |
| `scripts/demo_riksdag_report.py` (TRACKED) | Demo: Riksdag 2026-referensrapport | 0 referenser | **B** | Som ovan. |
| `scripts/demo_run_live_feed.py` (TRACKED) | Demo: publicerar run-watch-events mot körande API | 0 referenser | **B** | Som ovan. |
| `scripts/backfill_document_categories.py` (**UNTRACKED**) | Engångs-backfill av DocumentCategory-index ("Use when … never written") | 0 referenser i Makefile/CI/docs/tester; docstring säger uttryckligen engångs + kräver exklusiv tenant-lock | **B** | Behåll som engångsverktyg men dokumentera i `docs/` eller flytta till `scripts/oneoff/`. |
| `scripts/diagnose_document_channels.py` (**UNTRACKED**) | Opt-in nio-turns dokumentkanalsdiagnos | 0 referenser | **B** | Diagnostikverktyg; dokumentera eller arkivera. |
| `scripts/evaluate_36_avtl.py` (TRACKED) | Live 36 §-utvärdering i isolerad SQLite | Refereras i `docs/guides/research-36-eval.md:46-47` (`python -m scripts.evaluate_36_avtl`) | **—** | Levande — behåll. |
| `scripts/benchmark_channel_parity.py` (**UNTRACKED**) / `scripts/benchmark_document_channel_parity.py` (**UNTRACKED**) | Steg A resp. Steg B channel-parity-experiment | Båda dokumenterade i `docs/specs/channel-parity-step-a.md:35` resp. `docs/specs/deterministic-document-presentation-experiment.md:92` | **—** | Levande — behåll. (Två separata steg, inte dubbletter.) |
| `scripts/run_simulation_smoke.py:11` | `import sys` oanvänd | Ruff F401 | **A** | Ta bort importen. |
| `scripts/benchmark_prompt_configurations.py:651` | `require_anchor_sets_for_language` odefinierad (F821) | Ruff F821; funktionen finns i `app/services/anchor_store.py:224` men importeras inte | **B (bugg)** | Lägg till `from app.services.anchor_store import require_anchor_sets_for_language`. |

## 6. Ruff (kompletterande bevis)

`backend/.venv/bin/ruff check app scripts --select F401,F811,F841,F821 --output-format concise`:
```
scripts/benchmark_prompt_configurations.py:651:38: undefined-name: Undefined name `require_anchor_sets_for_language`
scripts/run_simulation_smoke.py:11:8: unused-import: [*] `sys` imported but unused
Found 2 errors.
```
Inga F401/F811/F841/F821 i `app/` — importytan är städad. (Fynd 1 är en verklig bugg, se avsnitt 0/5.)

## 7. Legacy-shims, döda flaggor och dubbletter (utöver modul-/def-listan)

| Fil:rad | Vad | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| `app/schemas/domain.py:337`; `app/api/ws.py:140,593`; `app/api/help.py:60`; `app/services/help_chat.py:115,205,228` | `ground_population`-flaggan är död end-to-end | `help_chat.py:117`: `del ground_population  # legacy WS/REST flag; SCB dist is always available`. **Ingen frontend/word-addin skickar fältet** (sökning i `frontend/src`, `word-addin/src` → 0 träffar). Schema-fältet har default `False` och påverkar inget | **A** | Ta bort fältet ur schema, WS-payload, help-API och help_chat-signaturer. |
| `app/services/oasis_run.py:155-157` | `_created_at_to_sort_key` — "Backward-compatible alias" | Används **bara** av `app/services/run_tick_context.py:7,27,85`, som importerar den privata aliasen | **B** (städkandidat, ej död) | Byt `run_tick_context` till `simulation.artifact.created_at_to_sort_key` och ta bort aliasen. |
| `app/services/oasis_run.py:190-192` | `_read_oasis_results` — "Backward-compatible alias" | Ingen referens alls utanför `oasis_run.py` (0 träffar repo-vid på namnet) | **A** | Ta bort aliasen och anropa `read_oasis_results` direkt. |
| `app/services/word/application.py` `UNRESOLVED_*` | Se avsnitt 4a | Strängvärden används som literals; konstanterna är oanvända | **B** | Ersätt literals med konstanter eller ta bort konstanterna. |
| `app/schemas/domain.py:1107-1115` | `expand_legacy_web_search` — mappar `enable_web_search` → nya flaggor | Endast legacy-mappning; `enable_web_search` är dokumenterat legacy i `backend/AGENTS.md` | **C** | Avsiktlig bakåtkompatibilitet i payload; behåll tills gamla körningar är migrerade, dokumentera sunset. |
| `app/api/runs.py:452`; `app/services/run_results.py:17-44`; `app/services/persona_chat.py:247` | `attempt_id == "legacy"` — lyfter äldre platt resultatstruktur | Hanterar historiska `results`-rader i DB | **C** | Dynamisk/data-driven bakåtkompatibilitet — **ta inte bort** utan DB-inventering (DB-audit äger). |
| `app/services/panel/result.py:87` | Legacy `DdPanelResult`-dump accepteras | Dataformat-kompatibilitet | **C** | Behåll; koppla till DB/migrationsbeslut. |

## 8. Topp-15: viktigaste fynden med rekommenderad åtgärd

| # | Fynd | Plats | Verdict | Åtgärd |
|---|---|---|---|---|
| 1 | `NameError` i dokumenterat benchmark-skript | `scripts/benchmark_prompt_configurations.py:651` | B (bugg) | Lägg till import av `require_anchor_sets_for_language`. |
| 2 | Legacy-revalideringsmodul, uttryckligen prod-förbjuden | `app/services/knowledge/revalidation.py` | A | Radera modul + cutover-tester; verifiera Alembic-oberoende. |
| 3 | Oinkopplad semantisk frågematchning + 3 döda settings | `app/services/research/question_semantic.py` + `app/config.py:215,218,219` | A/B | Antingen koppla in eller radera modul + settings. |
| 4 | Död env-config dokumenterad som aktiv | `.env.example:24-25` + `docs/guides/backend-setup.md:31-32` | A | Ta bort nycklarna ur exempel/docs (eller implementera läsning). |
| 5 | Test-only jobbsnapshot-helper (dubblett av prod-väg) | `app/services/job_watch.py` | B | Jämför med `api/workspace_job_watch.py`; ta bort om testet kan använda prod-vägen. |
| 6 | Död `ground_population`-flagga genom hela kedjan | 6 platser enligt avsnitt 7 | A | Ta bort fältet ur schema/WS/API/help_chat. |
| 7 | Test-only temporal invalidering (Graph v2-rest) | `app/services/graph_v2/temporal.py` | B | Ta bort med tillhörande tester om inte invalidering ska återinföras. |
| 8 | Test-only OverGraph-traversal (Jev-budget) | `app/services/overgraph/traversal.py` | B | Bekräfta att retrieval inte använder den; annars bort. |
| 9 | `JobHub`-alias utan användare | `app/realtime/hub.py:125` | A | Ta bort aliaset. |
| 10 | `owner_user_id_from_job` oanvänd | `app/auth/scope.py:12` | A | Ta bort funktionen. |
| 11 | `ProjektCreate`-schema oanvänt | `app/schemas/kund.py:39` | A | Ta bort modellen. |
| 12 | `get_or_none` oanvänd (LLM runtime settings) | `app/services/llm_runtime_settings.py:521` | A | Ta bort. |
| 13 | Oanvända OverGraph-research-API:er | `app/services/overgraph/research.py:156,411,434` m.fl. | B | Inventera OverGraph-anrop; ta bort oanvända API:er. |
| 14 | 3 engångs-demoskript utan referenser | `scripts/demo_{quick_report,riksdag_report,run_live_feed}.py` | B | Arkivera eller dokumentera; ej CI-relevanta. |
| 15 | `_read_oasis_results` alias utan referens | `app/services/oasis_run.py:190` | A | Ta bort aliaset; anropa `read_oasis_results`. |

## 9. Bilagor

- Full AST-analys: `/tmp/obsolete-audit/analysis.txt` (modul-reachability, router-mountning, 0-ref-definitioner, settings-tabell).
- Repo-vid ordgränsverifiering per definition: `/tmp/obsolete-audit/defs.txt`.
- Skript: `/tmp/obsolete-audit/analyze.py`, `/tmp/obsolete-audit/verify_defs.py` (körbara med Python 3.13; inga repot-ändringar).
- Inga filer i repot ändrades; inga formatters, migrationer eller nätverksanrop kördes.
