# Audit C — Obsoleta/döda testfall och testhjälpmedel

**Repo:** `/Users/erikfremred/socialism` · **Branch:** `fix/sme-group-chat-voice` (arbetskopia, ~613 modifierade + ~397 untracked filer)
**Omfattning:** `backend/tests/**`, `frontend/**`-tester, `word-addin/**`-tester. Backend-appkod, DB-schema och frontend-appkod auditeras av andra medlemmar.
**Läge:** read-only. Inga käll-/testfiler ändrade, inga installationer, inga nätverksanrop. Endast denna fil skriven.
**Datum:** 2026-10-18

## Metod (vad som faktiskt kördes)

| Steg | Kommando/teknik | Resultat |
|---|---|---|
| Inventering backend | `backend/.venv/bin/pytest --collect-only -q tests` | 3593 collected / 3595 totalt (2 smoke deselectade via `addopts`) |
| Sviter separat | `pytest --collect-only -q tests/integration`, `tests/research_reuse`, `-m smoke tests/smoke` | 21 / 227 / 2 tester |
| CI-kartläggning | läsning av `.github/workflows/ci.yml` (rad 110–111, 134, 190), `backend/pyproject.toml:85–91`, `Makefile:157` | se tabell nedan |
| Statisk AST-analys | egna skript i `/tmp/obsolete-audit/` (`analyze.py`, `analyze2.py`, `imports.py`, `mocktargets.py`, `dedupe.py`, `routes.py`) | importupplösning, dubbletter, fixtures, monkeypatch-mål, settings-attribut, skip-mönster |
| Döda hjälpmoduler | importgraf + `grep` i hela repot (inkl. `scripts/`, docs) | verifierade manuellt — inga falska "döda" moduler kvar |
| Frontend/word-addin | statisk importupplösning, `it/test/expect`-räkning, dubblett-titlar, git-status | se avsnitt 5 |
| Riktad körning | `pytest tests/test_anchor_pool.py::test_pool_add_and_remove` (endast för att verifiera att routrar är monterade) | 1 passed (~1 s) — ingen full svit körd |

**Viktigt om arbetskopian:** 42 testfiler under `backend/tests` är untracked och 34 är modifierade; 17 frontend/word-addin-testfiler är untracked. Dessa är **WIP i feature-branchen** och klassas nedan som WIP (C), inte som obsoleta. Tracked-status är verifierad med `git ls-files --error-unmatch` från repo-roten.

## Sammanfattning per kategori

| Kategori | Antal fynd | Varav A | B | C |
|---|---|---|---|---|
| 1. Tester som aldrig kan köras/faila | 3 | 2 | 1 | 0 |
| 2. Tester för borttagen funktionalitet | 2 | 2 | 0 | 0 |
| 3. Dubbletter / nära-identiska kopior | 7 | 0 | 5 | 2 |
| 4. Oanvända fixtures/helpers/imports | 1 (+2 verifierade falska positiver) | 1 | 0 | 2 |
| 5. Sviter som alltid skippas i CI | 7 | 0 | 3 | 4 |
| 6. WIP/experiment (ej obsolet) | 4 | 0 | 0 | 4 |

**Huvudfynd:** den enskilt största obsoleta enheten är `tests/test_evidence_revalidation.py` (11 testfall) som bara testar `app/services/knowledge/revalidation.py` — en tracked modul vars egen docstring säger att den är legacy och att produktionskod inte får anropa den. Modulen har **noll** importörer i `app/` och `scripts/`.

---

## 1. Tester som aldrig kan köras/faila

| Fil:rad | Test/fixture | Varför obsolet | Bevis | Verdict | Förslag |
|---|---|---|---|---|---|
| `backend/tests/test_expert_async_tools.py:161` | `test_tool_call_ack_does_not_make_a_discarded_text_request` | Guard mot `complete_text` kan aldrig trigga: målet finns inte i modulen, och `raising=False` gör monkeypatchen till en tyst no-op | `monkeypatch.setattr("app.services.expert_async_tools.complete_text", unused_text, raising=False)`; `app/services/expert_async_tools.py` importerar bara `complete_with_tools` (rad 15); `complete_text` finns inte någonstans i modulen | **A** | Ta bort monkeypatch + `unused_text` (död kod i testet), eller peka på verklig symbol om avsikten är att skydda ett framtida anrop. Testets `reply`-assertion behålls |
| `backend/tests/test_evidence_revalidation.py:115,119,249,270,315,326,348,365,395,412,467` | 11 testfall som alla testar `app/services/knowledge/revalidation.py` | Testar en modul som enligt egen docstring är "Legacy claim/event revalidation retained only for the cutover test suite. Production research code must not call this module." Modulen importeras bara av tester | `app/services/knowledge/revalidation.py:1–5`; importgraf: 0 träffar i `app/`/`scripts/` utanför modulen själv; enda importörer: `tests/test_evidence_revalidation.py:36`, `tests/test_knowledge_tenant_boundary.py:67`. Tabellen `evidence_set_revalidations` (modell `app/database/models.py:2092`) refereras utanför modellen bara av legacy-modulen + dessa tester | **A** | Efter cutover: ta bort modul + tabell/migration + hela testfilen. Tills dess: flytta till egen katalog/markera `xfail`/`legacy` så den inte räknas som aktiv täckning |
| `backend/tests/test_expert_chat_evidence.py:255` | `test_memory_update_is_scheduled_without_waiting` | Testet beräknar `pending = [task for task in memory_tasks if not task.done()]` men har **ingen assertion** i hela kroppen; det som faktiskt verifierar något är bara `asyncio.wait_for(started.wait(), timeout=1)` | AST: noll `assert`/`pytest.raises` i funktionen; sista raden är en list-comprehension vars värde aldrig används | **B** | Lägg `assert pending`/`assert not pending` (beroende på avsedd semantik) eller ta bort den döda raden |

## 2. Tester för borttagen funktionalitet

| Fil:rad | Test/fixture | Varför obsolet | Bevis | Verdict | Förslag |
|---|---|---|---|---|---|
| `backend/tests/test_evidence_revalidation.py` (hela filen) | 11 testfall mot legacy-revalidation | Enda testtäckningen för en modul som inte anropas av produktion (se ovan) | modulens docstring + importgraf | **A** | se ovan |
| `backend/tests/test_knowledge_tenant_boundary.py:597` | `test_revalidation_only_finds_evidence_sets_in_tenant_scope` | Det enda testet i filen som beror på legacy-modulen (`graph_impact_from_event`, `affected_frozen_evidence_sets`, rad 661–670); resten av filen testar levande tenant-scope | `grep` i filen: enda användningen av revalidation-symbolerna är rad 661–670; import rad 67–70 | **A** (för just detta test) | Ta bort testet tillsammans med legacy-modulen; behåll övriga tenant-boundary-tester |

**Verifierade negativa resultat (inga fynd):**
- Inga tester refererar de borttagna config-fälten `document_knowledge_llm_max_tokens` / `document_knowledge_llm_timeout_seconds` (de togs bort i `backend/app/config.py` i arbetskopian). `grep -rn "document_knowledge_llm" backend/tests` → 0 träffar. Inget att städa.
- Alla `from app... import ...` i backend-testerna löser upp till existerande moduler/symboler (AST-upplösning över `package __init__`-reexports). Inga importer av borttagna moduler.
- Alla `monkeypatch.setattr("app....")`-strängmål utom `expert_async_tools.complete_text` (ovan) löser upp till existerande modul + attribut.
- Alla `settings.<attr>` i tester finns som fält/property (154 Settings-fält + properties kontrollerade).
- `tests/test_research_answer_review.py:80` (`pytest.raises(ModuleNotFoundError): importlib.import_module("app.services.graph_v2.revalidation")`) är en **avsiktlig negativ guard** för borttagen Graph v2-revalidation — inte obsolet (C).

## 3. Dubbletter / nära-identiska kopior

Exakt-normaliserad AST-jämförelse av alla 3131 testfunktioner gav **0 exakta kopior** (kroppar skiljer sig). Nedan är manuellt verifierade nära-dubbletter.

| Fil:rad | Test | Dubblett av | Bevis | Verdict | Förslag |
|---|---|---|---|---|---|
| `backend/tests/test_oasis_actions_readback.py:35` | `test_population_action_names_default_excludes_create_post` | `backend/tests/test_action_catalog.py:26` (samma namn) | Samma funktion `population_action_names`; readback-versionen är en superset av assertionerna | **B** | Ta bort readback-kopian; behåll `test_action_catalog.py:s` (som redan täcker `INTERVIEW`/ordning) |
| `backend/tests/test_oasis_actions_readback.py:49` | `test_population_action_names_reddit_omits_repost_quote` | `backend/tests/test_action_catalog.py:34` (samma namn) | Samma fyra första assertions; readback lägger till `CREATE_COMMENT`/`TREND` | **B** | Slå ihop: flytta de två extra assertionerna till action_catalog-testet och ta bort readback-kopian |
| `backend/tests/test_oasis_actions_readback.py:58` | `test_population_action_names_with_create_post` | `backend/tests/test_action_catalog.py:41` (`..._with_create_post_first`) | Samma beteende (`names[0] == "CREATE_POST"`, reddit utan REPOST) | **B** | Samma som ovan |
| `backend/tests/test_oasis_actions_readback.py:109,117` | `test_created_at_sort_key_handles_timestep_and_iso`, `test_max_event_time_iso_datetime` | `backend/tests/test_artifact_reader.py:84,187` | Samma två `sqlite3`-scenarier; readback testar legacy-aliassen i `app/services/oasis_run.py` (`_created_at_to_sort_key`, `_max_event_time`), artifact_reader testar kanoniska `app/services/simulation/artifact/reader.py`. Legacy-aliasen används fortfarande (`app/services/run_tick_context.py:7`, `oasis_run.py:461`) → dubblett av *beteende*, inte av död kod | **B** | Behåll en uppsättning: låt `test_artifact_reader.py` äga sort-key/max-event-time; i readback behåll endast `_read_oasis_results`-wrapptesterna (rad 146, 243) |
| `backend/tests/test_expertgranskning_word_review.py:2268` | `test_reviewed_text_from_job_request_walks_sections` | `backend/tests/test_word_anchors.py:92` (samma namn) | Samma funktion `reviewed_text_from_job_request`; word_review-versionen har en extra implicit-rubrik-assertion | **B** | Ta bort en av dem (behåll den i `test_word_anchors.py` som är modulnära; flytta ev. extra assertion dit) |
| `backend/tests/test_document_catalog_ingest.py:170` vs `backend/tests/test_document_qa_outbox.py:201` | `test_writeback_releases_the_only_connection` | varandra (samma namn) | Två olika writebacks (`document_qa.catalog_apply` vs `document_qa.apply`) med samma one-connection-mönster. Inte samma kod → ingen dubblett | **C** | Ingen åtgärd; ev. döp om för tydlighet |
| `backend/tests/test_execution.py:391` vs `backend/tests/test_execution_api.py:1049` | `test_clone_rejects_source_without_evidence` | varandra (samma namn) | Service-lager vs HTTP-lager; olika assertions (exception vs 409) | **C** | Ingen åtgärd |

## 4. Oanvända fixtures / helpers / imports

| Fil:rad | Fixture/helper | Varför obsolet | Bevis | Verdict | Förslag |
|---|---|---|---|---|---|
| `backend/tests/conftest.py:363` | `bolag_client` | Fixture som aldrig används: noll test-parametrar, noll `usefixtures`, inga andra fixtures beror på den. Testfilerna skapar egna `ScopedClient`/`_bolag_token()` i stället | `grep -rn "bolag_client" backend/tests`: endast definitionen + lokala variabler i `test_actor_profiles.py:50,150` och en lokal `_bolag_token` i `test_websocket.py:99` | **A** | Ta bort fixturen (eller använd den i de tester som idag duplicerar dess logik) |

**Falska positiver som verifierats bort (viktigt att inte "städa"):**
- `backend/tests/conftest.py:194` `graph_retrieval_embeddings` ser oanvänd ut i param-räkningen men används via `pytestmark = pytest.mark.usefixtures("graph_retrieval_embeddings")` i 5 filer (`test_research_progress.py:50`, `test_research_question_attempt_worker.py:45`, `test_research_loop.py:49`, `test_research_planner.py:55`, `test_iterative_knowledge_question_research.py:57`). **Behåll.**
- Importer som ser oanvända ut men är avsiktliga fixture-reexports: `test_research_shadow_concurrency.py:11` (`jev_settings  # noqa: F401 -- shared fixture`), `test_workspace_existing_source.py:18`, `test_workspace_selected_memory.py:13`, `test_workspace_agent_deployment.py:10`, `test_workspace_memory_policy.py:20` (`provider as provider`, `single_connection_provider as single_connection_provider`). **Behåll.**
- Alla testhjälpmoduler under `backend/tests/` som såg oanvända ut (`tests/research_reuse/coverage_live.py`, `sufficient_live.py`, `jev_backoff.py`, `jev_window_controls.py`) är **inte** döda: de importeras i funktionskroppar i respektive test (`test_gap_coverage.py:175`, `test_sufficient_live.py:10`, `test_jev_backoff.py:11`) och/eller av `backend/scripts/check_*.py` (t.ex. `scripts/check_research_gap_coverage.py:25`, `scripts/check_sufficient_answer_reuse.py:17`, `scripts/check_jev_windows.py:16`). **Behåll.**

## 5. Sviter som aldrig körs i CI (CI-relevans)

**Vad CI faktiskt kör** (`.github/workflows/ci.yml`):

| Jobb | Kommando | Sviter |
|---|---|---|
| `backend` (matris 4 splits) | rad 110–111: `pytest -m "not smoke and not research_reuse"` | allt under `tests/` **utom** smoke + research_reuse, **inkl. `integration`-markerade tester** |
| `research-reuse` | rad 134: `pytest tests/research_reuse -m research_reuse` | 227 mocked reuse-kontrakt |
| `postgres-schema` | rad 190: `pytest tests/test_shared_chunk_postgres.py -m integration` | endast 2 tester |
| `frontend` | `pnpm test` (vitest) | 63 filer / 318 testfall |
| `word-addin` | `pnpm test && tsc -b` | 16 filer / 102 testfall |
| `knowledge` | `make knowledge-validate` | ej tester |

`backend/pyproject.toml:86` har `addopts = "-m 'not smoke'"`; `Makefile:157` (`make test-backend`) kör `pytest` utan extra `-m` → **lokalt körs även research_reuse + integration** (integration skippar sig själva). `pytest-xdist`-splitsen använder `.test_durations`.

| Fil:rad | Test/svit | Varför obsolet i CI | Bevis | Verdict | Förslag |
|---|---|---|---|---|---|
| `backend/tests/test_research_36_integration.py:242,266` | `test_live_resolver_and_fetch` (8 parametriserade fall) + `test_live_model_nja_and_sou` | Markerade `integration` men CI filtrerar **inte** på `integration` → de körs och skippar alltid; kräver CLI-flaggor som CI aldrig skickar | `pytest.skip("requires --live-research-sources")` rad 247, `"requires --live-research-model …"` rad 270; CI-rad 110–111 saknar dessa flaggor | **B** | Flytta till `tests/integration/` med samma opt-in-mönster som övriga, eller lägg till en CI-step med flaggorna (dyrt: riktiga nätanrop) |
| `backend/tests/test_answer_review_postgres.py:29–30` | `test_postgres_migration_and_concurrent_candidate_workers` | `skipif(not POSTGRES_URL)`, och `postgres-schema`-jobbet kör bara `test_shared_chunk_postgres.py` → testet körs **aldrig** i CI trots att jobbet har Postgres | ci.yml:183–190 (endast shared_chunk); skipif rad 30 | **B** | Lägg till testet i `postgres-schema`-jobbet (det är exakt den miljön det behöver) |
| `backend/tests/integration/` (8 opt-in live-tester) | `test_jev_competency_live.py:20`, `test_semif_competency_live.py:26`, `test_live_speech_opening_live.py:30`, `test_shown_document_live.py:32` (2 tester), `test_expert_consult_prompt_live.py:38`, `test_expert_find_show_e2e_live.py:39`, `test_supabase_vector_live.py:24` (skipif env) | Alla kräver env-flaggor/riktiga nycklar som CI inte sätter → alltid skippade i CI (och i `make test`) | respektive `_ENV_FLAG`/`skipif`; filernas docstrings säger "Opt-in. Default pytest skips it, including CI" | **C** (avsiktligt) | OK som manuella, men överväg att flytta dem till `scripts/`/dokumentera i README så de inte ser ut som CI-täckning. 13 andra tester i `tests/integration/` (overgraph/chain, lokal SQLite) körs faktiskt i CI-matrisen |
| `backend/pyproject.toml:87–91` (marker-definition) | markern `integration` | Dokumentationen säger "skipped in default CI", men **ingen** filter (`-m "not integration"`) finns i CI eller Makefile. Markern gör alltså inte det den påstår; nya `tests/integration/*` med lokal SQLite (t.ex. untracked `test_document_find_overgraph.py`, `test_find_documents_chain.py`) körs i CI-matrisen | `grep -n "not integration" .github Makefile` → 0 träffar; `pytest -m integration --collect-only` → 33 tester varav 13 faktiskt körs i CI | **B** | Antingen lägg `-m "not smoke and not integration and not research_reuse"` i CI + separat integration-jobb, eller uppdatera marker-beskrivningen till sanningen |
| `backend/tests/smoke/` (2 tester) | `test_oasis_simulation_smoke.py`, `test_oasis_simulation_smoke_reddit.py` | Exkluderas av `addopts` (`not smoke`) och nämns inte i CI → körs aldrig automatiskt. Kräver `camel-oasis` + riktig DeepSeek-nyckel | `pyproject.toml:86`; `tests/smoke/conftest.py:31,41` skip-villkor; `grep "smoke" .github/workflows/ci.yml` → endast i `-m`-filtret | **C** (avsiktligt manuell) | Behåll, men dokumentera i README att de bara körs manuellt (`uv sync --extra oasis`) |
| `experiments/overgraph_ingest/tests/` (82 `test_*.py`) | hela experiments-sviten | Ligger utanför `testpaths=["tests"]` och har egen `pyproject.toml`; körs aldrig av CI eller `make test` | `backend/pyproject.toml:85`; `experiments/overgraph_ingest/pyproject.toml` | **C** (separat experimentprojekt) | Ingen åtgärd om experimentet är levande; arkivera katalogen om det är avslutat |
| `integration-tests/` (9 fristående skript) | `check_*_live.py`, `*_setup.py` | Inte pytest-svit; refereras inte av CI/Makefile. Manuella live-checkar | `ls integration-tests/*.py` → 9; `grep -rn "integration-tests" .github Makefile` → 0 | **C** | OK som manuella verktyg; överväg `scripts/` för upptäckbarhet |

## 6. WIP / experiment — inte obsolet, men flaggas för lead

| Område | Omfattning | Bedömning | Rekommendation |
|---|---|---|---|
| `backend/tests/**` untracked | 42 filer (t.ex. `test_document_qa*.py`, `test_sme_quick_draft*.py`, `test_workspace_tool_*.py`, `tests/integration/test_document_find_overgraph.py`, `tests/integration/baselines/`) | Ny funktionalitet i feature-branchen, inte gammal kod → **skall inte** klassas som obsolet | Granska i PR; se till att `baselines/` commitas samtidigt som testerna som läser den |
| `backend/tests/**` modifierade | 34 filer | WIP | — |
| Experiment-harness-tester (untracked) | `test_benchmark_document_presentation.py`, `test_channel_parity_experiment.py`, `test_document_channel_diagnostic.py`, `test_document_channel_parity_step_b.py`, `test_expert_prompt_routing_baseline.py` | Tester för engångs-/benchmarkskript (`scripts/document_presentation_benchmark/…`) + frusna baselines. Hör sannolikt inte i CI-matrisen på sikt | **C** — överväg egen markering (t.ex. `@pytest.mark.benchmark`) eller flytt till `experiments/` när mätningen är klar |
| `frontend`/`word-addin` untracked tester | 17 filer | WIP | — |

## 7. Frontend och word-addin — resultat

| Kontroll | Resultat |
|---|---|
| Saknade lokala importer i testfiler (`.ts/.tsx`, inkl. `vi.mock`) | **0** — alla 63 frontend- + 16 word-addin-testfiler löser upp sina importer |
| Tester mot borttagna moduler | Inga. Borttagna `frontend/src/products/sme/liveSpeechVad.ts` + `liveSpeechVad.test.ts` är ersatta av `speechVad.ts` + `speechVad.test.ts`; inga kvarvarande referenser till `liveSpeechVad` |
| `it.skip`/`test.skip`/`describe.skip`/`.only` | **0** |
| Tester utan `expect` | **0** (318 respektive 102 testfall; alla filer har minst lika många `expect` som testfall) |
| Dubblett-titlar mellan filer | **0** |
| i18n-nyckel-snapshots mot borttagna nycklar | Inga snapshot-tester finns i frontend/word-addin → inget att städa |

Slutsats: **inga obsoleta testfall hittade i frontend eller word-addin**; enda anmärkningen är WIP-filerna ovan.

## 8. Topplista — 15 rekommenderade åtgärder (prioritetsordning)

| # | Åtgärd | Filer | Verdict | Effekt |
|---|---|---|---|---|
| 1 | Ta bort legacy-revalidation-modulen + dess 11 tester + tabell/migration efter cutover | `backend/app/services/knowledge/revalidation.py`, `backend/tests/test_evidence_revalidation.py`, `backend/alembic/versions/121_evidence_revalidation.py` | A | Tar bort ~530 testrader som bara testar död produktionskod |
| 2 | Ta bort `test_revalidation_only_finds_evidence_sets_in_tenant_scope` | `backend/tests/test_knowledge_tenant_boundary.py:597` | A | 1 test som hänger på legacy-modulen |
| 3 | Ta bort död monkeypatch + `unused_text` | `backend/tests/test_expert_async_tools.py:161` | A | Guard som aldrig kan trigga |
| 4 | Ta bort oanvänd `bolag_client`-fixture | `backend/tests/conftest.py:363` | A | Död fixture |
| 5 | Avdubbla `test_oasis_actions_readback.py` mot `test_action_catalog.py` + `test_artifact_reader.py` | `backend/tests/test_oasis_actions_readback.py:35,49,58,109,117` | B | ~5 dubblett-testfall |
| 6 | Avdubbla `test_reviewed_text_from_job_request_walks_sections` | `backend/tests/test_expertgranskning_word_review.py:2268` vs `test_word_anchors.py:92` | B | 1 dubblett |
| 7 | Lägg `test_answer_review_postgres.py` i `postgres-schema`-jobbet | `.github/workflows/ci.yml`, `backend/tests/test_answer_review_postgres.py` | B | Test som aldrig körs i CI får äntligen köras |
| 8 | Flytta/flagga `test_research_36_integration.py`-liven | `backend/tests/test_research_36_integration.py:242,266` | B | 9 testfall som alltid skippas i CI blir tydligt manuella |
| 9 | Rensa integration-marker-semantiken (filter eller dokumentation) | `backend/pyproject.toml:87–91`, `.github/workflows/ci.yml:110–111` | B | Markern lovar fel sak idag |
| 10 | Dokumentera opt-in live-tester i README (env-flaggor) | `backend/tests/integration/` (8) | C | Minskar risk att de antas vara CI-täckning |
| 11 | Behåll men dokumentera smoke som manuell | `backend/tests/smoke/` (2) | C | — |
| 12 | Avgör experiment-harness-testernas hemvist | `backend/tests/test_benchmark_document_presentation.py` m.fl. (untracked) | C | Undvik att engångsmätningar blir CI-krav |
| 13 | Commit `tests/integration/baselines/` ihop med testerna som läser den | `backend/tests/integration/baselines/` (untracked) | C | Annars failar nya tester i CI |
| 14 | Lägg till assertion i `test_memory_update_is_scheduled_without_waiting` | `backend/tests/test_expert_chat_evidence.py:255` | B | Tar bort död sista rad |
| 15 | Arkivera/ägardokumentera `experiments/` och `integration-tests/` | respektive katalog | C | Tydliggör att de aldrig körs i CI |

## 9. Antaganden och osäkerheter

- **Legacy-revalidationens framtid** avgörs av om cutover-sviten fortfarande behövs. Docstringen säger uttryckligen att modulen behålls "only for the cutover test suite" → om cutovern är klar är fynd 1–2 rena borttagningar; annars är de "avsiktligt transitional" (men bör då markeras så de inte räknas som produktionstäckning).
- **Untracked-filer** (42 backend, 17 frontend/word-addin) kan inte bedömas som obsoleta eftersom de är ny WIP i feature-branchen; de kan dock redan nu vara överflödiga dubbletter av tracked tester (ingen sådan dubblett har påvisats utöver `test_oasis_actions_readback.py`, som är tracked).
- **Ingen full pytest-körning** gjordes (enligt uppdrag); slutsatserna bygger på `--collect-only`, riktad enstaka körning, AST/importgraf och `grep`. Skip-beteenden i CI är statiskt verifierade mot workflow-filen, inte genom att köra CI-lokalt.
- Backend-kodfynd som ligger utanför testområdet (t.ex. legacy-modulens existens, `EvidenceSetRevalidation`-tabellen) rapporteras här endast som stödbevis — backend-/DB-auditen äger åtgärden.
