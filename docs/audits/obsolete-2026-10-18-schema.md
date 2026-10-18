# Audit B — obsoleta databastabeller, kolumner och migrationer

**Repo:** `/Users/erikfremred/socialism` (arbetskopia, branch `fix/sme-group-chat-voice`)
**Scope:** endast schema/migrationer. Read-only: ingen DB ansluten, inga migrationer körda, enda skrivning är denna fil.
**Datum:** 2026-10-18

## 1. Sammanfattning

| Mått | Värde |
| --- | --- |
| Metadata-tabeller (`Base.metadata.tables`) | **114** |
| `.py`-migrationer i `backend/alembic/versions/` | **187** (164 tracked + 23 untracked, 167–189) |
| Revisioner i kedjan | 187 — **1 head** (`189_quick_lines_never_refuse`, verifierat med `alembic heads`), 1 rot (`001_initial`), 2 merge-revisioner (035, 048) |
| Trasiga/orphan `down_revision` | **0** |
| Tabeller som skapas i `upgrade()` men saknas i metadata (drift) | **0** |
| Metadata-tabeller som ingen migration skapar | **0** |
| Tabeller i metadata som är borta vid head | **0** |
| Tabeller i metadata helt utan produktionsreferens | **1** → `evidence_set_revalidations` |
| Tabeller skapade och senare droppade i `upgrade()`-historiken | 3 (`catalog_lists` återskapad via rename, `graph_fact_revalidations`, `graph_question_revalidation_work`) |
| Kolumner i metadata | 478 unika namn; **0** helt orefererade, 3 dynamiskt refererade (`runs.live_progress_*`) |
| `add_column` / `drop_column` i upgrade-historiken | ~138 / 9 |
| `create_index` / `drop_index` i upgrade-historiken | 264 / 5 |

**Huvudslutsats:** schemat är i synk med koden. Migrationskedjan är linjär och intakt (2 medvetna merges), det finns ingen schema-drift, och praktiskt taget varje tabell/kolumn används av applikationskoden. Den enda bekräftat oanvända tabellen är `evidence_set_revalidations` (legacy cutover-modul som bara testkoden importerar). Dessutom finns två **pgvector-tabeller skapade med rå DDL** (`expert_memories`, `expert_memories_entities`) som sannolikt är övergivna sedan Mem0 bytte till OverGraph som vector store — de syns inte i metadata och kräver manuell DB-verifiering innan drop.

## 2. Metod (kort)

1. Importerade alla modeller via `backend/app/database/__init__.py` + `Base.metadata` → `metadata_tables.json` (114 tabeller).
2. AST-parsade samtliga 187 migrationsfiler: både `revision = "…"` (Assign) och `revision: str = "…"` (AnnAssign), tuple-`down_revision` expanderad, och **hjälpfunktioner reachable från `upgrade()`/`downgrade()`** (t.ex. `_create_workspaces()` i 149) samt `with op.batch_alter_table(...) as batch/batch_op:`-block (båda variabelnamnen finns; 71+ block). Byggde tabell- och kolumnlivscykel i topologisk ordning (Kahn) samt separat `upgrade`/`downgrade`.
3. Referensräkning per tabell: modellklass, `__tablename__`-sträng, `from app.database… import` över `backend/app`, `backend/scripts`, `backend/tests`, `integrations`, `frontend/src`, `word-addin`.
4. Modul-reachability från `app.main` + `backend/scripts` för att hitta tabeller som bara används av död/test-only kod.
5. Kolumnreferensräkning (478 unika kolumnnamn) utanför modellfilerna.
6. Läste lokal sqlite `backend/data/opinionssimulator.db` **read-only** (`mode=ro`) och diffade tabeller/kolumner mot metadata.
7. Dubbelcheck: `backend/.venv/bin/alembic heads` (offline, ingen DB) → `189_quick_lines_never_refuse (head)`.

Artefakter i `/tmp/obsolete-audit/`: `metadata_tables.json`, `migrations.json`, `refs.json`, `columns.json`, `import_graph.json`, `sqlite_diff.json`, skripten `parse_migrations.py`, `refs_fast.py`, `columns_fast.py`, `import_graph.py`, `sqlite_columns.py`.

## 3. Fynd — tabeller

Verdict: **A** = bekräftat obsolet (eller redan borttagen i kedjan), **B** = sannolikt obsolet (kräver en verifiering), **C** = osäker/falsk-positiv-risk → behåll.

| # | Tabell | Definierad i | Referenser / bevis | Verdict | Förslag |
| --- | --- | --- | --- | --- | --- |
| 1 | `evidence_set_revalidations` | `backend/app/database/models.py:2092` (klass), `:2095` (`__tablename__`), relation `:2086`; skapad i `backend/alembic/versions/121_evidence_revalidation.py:26` (tracked) | **1** app-fil: `backend/app/services/knowledge/revalidation.py` — filens docstring `:1`: *"Legacy claim/event revalidation retained only for the cutover test suite. Production research code must not call this module."* Inga icke-test-importers (grep `knowledge.revalidation` → 0 träffar i `app/` utanför modulen själv). Modulen är inte reachable från `app.main`/scripts. Test: `tests/test_evidence_revalidation.py:18,259` + `tests/test_knowledge_tenant_boundary.py:13,670`. Relaterade döda inställningar: `app/config.py:91-92,259-260`. | **A** | Ny drop-migration (nästa revision efter 189) + ta bort modell/relation; radera legacy-modul + `test_evidence_revalidation.py`, justera tenant-boundary-testet. Koordinera med Audit A (kod) och Audit C (tester). |
| 2 | `graph_fact_revalidations` | skapad `138_graph_fact_revalidation.py:25`, droppad `142_drop_graph_revalidation_queues.py:17` | 0 kodreferenser utanför migrationer; endast tester asserterar frånvaro (`tests/test_graph_v2.py:224`, `tests/test_alembic_graph_reconcile.py:52,74,83`). 142:s docstring: *"Drop unused Graph v2 question/fact revalidation queues."* | **A** (redan åtgärdad) | Ingen åtgärd — historiken är korrekt. Squash-kandidat, se §5. |
| 3 | `graph_question_revalidation_work` | skapad `139_graph_question_revalidation_work.py:13`, droppad `142_drop_graph_revalidation_queues.py:16` | Samma som #2. | **A** (redan åtgärdad) | Ingen åtgärd. |
| 4 | `expert_memories` (pgvector, **ej** i metadata) | rå DDL i `backend/alembic/versions/106_mem0_postgres_storage.py:66-77` (tracked) | Endast strängen `"expert_memories"` som Mem0-*collection name*: `app/config.py:136`, `app/services/overgraph/mem0_store.py:35,55`. Mem0 konfigureras nu med `"provider": "overgraph"`: `app/services/expertgranskning/memory.py:198-205`. Inga SQL-referenser till pgvector-tabellen. `MEM0_PGVECTOR_MINCONN/MAXCONN` (`memory.py:37-38`) är oanvända rester. | **B** | Verifiera i Supabase att tabellen är tom/оанvänd; lägg därefter postgres-only `DROP TABLE IF EXISTS expert_memories` i ny migration. Kräver DB-läsning som låg utanför auditen. |
| 5 | `expert_memories_entities` (pgvector, **ej** i metadata) | rå DDL i `106_mem0_postgres_storage.py:66-77` (samma loop) | Inga kodreferenser alls. `docs/specs/overgraph-knowledge-engine.md:130`: *"Entitetslänkar som idag ligger i expert_memories_entities blir noder och kanter i minneskatalogen"* → datamigrering planerad, tabellen är på väg bort. | **B** | Som #4, men kräver först att eventuella entitetslänkar migrerats/verifierats. |
| 6 | `mem0_history`, `mem0_messages` (rå DDL, ej i metadata) | `106_mem0_postgres_storage.py:29-64` | Används aktivt via `PostgresHistoryManager`: `app/services/expertgranskning/mem0_postgres_history.py:54,82,111,129,170`. | **C** | **Behåll.** Rå SQL/DDL utanför metadata — får inte flaggas som obsolet. |
| 7 | `workspace_chats` + `workspace_chat_messages` (149) vs `workspace_conversation_sessions` + `workspace_conversation_events` (151) | `149_workspaces.py:69,98`; `151_live_voice_workspaces.py:65,130` | Båda familjerna aktivt använda: workspace_chat: 8/7 app-filer; conversation: 6/4 app-filer (bl.a. `services/workspace_chat_turn.py`, `workspace_conversation_events.py`, `voice_workspace_inbox.py`). | **C** | **Behåll.** Parallell persistence för text-chat vs live-voice/konversation, inte dubblering. Konsolideringsidé endast om produktbeslut fattas. |
| 8 | `knowledge_entities` + `knowledge_relationships` (119) vs `graph_nodes` + `graph_facts` (127) | `119_knowledge_entities.py:22,42`; `127_graph_v2.py:24,51` | Båda skrivs: knowledge-lagret via `app/services/knowledge/persist.py`, `graph_v2/legal_writeback.py`; Graph v2 är kanonisk för reuse enligt `backend/AGENTS.md`. 4/3 app-filer för knowledge-tabellerna. | **C** | **Behåll.** Dubbel kunskapsmodell är dokumenterad pågående arkitektur, inte obsolet. |
| 9 | `raw_sources`, `domain_research_results`, `research_claims` (111) vs `evidence_sources`, `evidence_passages`, `text_units` (109/115) | `111_raw_domain_claims.py:88,105,130`; `109_canonical_evidence.py:106,117`; `115_canonical_text_units.py:141` | Båda används: `evidence_set_items` har både `passage_id` (kanonisk TextUnit-väg) och `domain_result_id` (legal/reuse-väg); `api/execution.py`, `research/answer_review.py`, `lagen_nu/research_source.py`, `execution/service.py`. | **C** | **Behåll.** Dubbel evidenslagring är aktiv och läses i API; `domain_result_id` är inte död. |
| 10 | `knowledge_question_evidence_links` | `backend/app/database/models.py:2782` (skapad i migration efter 115) | 1 app-fil: `app/services/research/question_graph_sql.py` — används av `answer_capture.py`, `question_prepare.py`, `composition.py` (reachable produktionskod). AGENTS kallar Question→Evidence links "legacy", men de skrivs/läses fortfarande. | **C** | **Behåll** till dess att Graph v2-only-writeback är genomförd; följ upp mot docs. |
| 11 | `catalog_lists` | skapad `005_catalog_lists.py:20`, droppad `013:130`, återskapad via `rename_table("catalog_lists_new", "catalog_lists")` `013:40,131` | Slutläget korrekt: tabellen finns i metadata och används (`api/catalog.py`, `services/catalog_store.py`). Migrationen är bara en ombyggnad (SQLite-batch-mönster). | **C** (behåll) | Ingen åtgärd; endast squash-kandidat, se §5. |
| 12 | `configurations.prompts` (JSON-kolumn) | `backend/app/database/models.py:546` | Runtime-prompter läses numera via `prompt_fields`/`prompt_overrides` (`backend/AGENTS.md`: *"not from … `Configuration.prompts`"*), men kolumnen serialiseras och skrivs fortfarande av `app/api/configurations.py:92,218,255` och läses av frontend-editorn. | **C** | **Behåll tills vidare.** Verifiera i frontend om editorn slutat skicka `prompts`; därefter kan kolumnen pensioneras i egen migration. |
| 13 | `runs.live_progress_main/a/b` | `backend/app/database/models.py:284-286`; migration `029_run_live_progress.py:21-31` | **0** statiska referenser — men nås dynamiskt: `app/services/run_live_progress.py:15-18` `f"live_progress_{variant_id}"` + `getattr/setattr(:22,34,47)`. | **C** | **Behåll.** Klassisk falsk positiv; får ej flaggas utan dynamikanalys. |
| 14 | `kunder.organization_name/number, address_line1/2, postal_code, city, country_code, profile_revision` | `backend/app/database/models.py:31-39`, `:40` | Låg statisk träffbild (1–8), men nås dynamiskt via `getattr/setattr` i `app/services/profiles.py:12,21,36-37` (`PROFILE_FIELDS`/`ORGANIZATION_FIELDS` i `app/schemas/profiles.py`). | **C** | **Behåll.** Falsk-positiv-risk; dynamisk fältuppsättning. |
| 15 | `shared_text_chunks` + `text_units.text` | `shared_text_chunks` skapad `e8c2f4a1b6d0_shared_text_chunks.py:73` (tracked, hash-revision mellan 141 och 142); `text_units.text` droppad `:84` | `shared_text_chunks` används av `knowledge/shared_chunks.py`, `live_speech_stt_terms.py`. Kolumnen `text_units.text` är borta (korrekt ersatt av chunk-tabellen). | **A** (kolumn redan borttagen) | Ingen åtgärd. Hash-namngiven revision är kosmetiskt udda men fungerar i kedjan — döp inte om. |

## 4. Fynd — kolumner (sammanfattning)

- **Ingen** metadata-kolumn är helt orefererad i kod (478 unika namn kontrollerade). Endast 3 "nollträffar": `runs.live_progress_main/a/b`, alla dynamiska → **behåll**.
- Kolumner som redan tagits bort i historiken (A, ingen åtgärd): `configurations.prompt_text` (012), `panel_expert_profiles.module` (044), `expertgranskning_results.comment_id/status` (069), `knowledge_claims.document_id/document_version_id` (126), `text_units.text` (e8c2f4a1b6d0).
- Kolumn-churn (adderad och senare droppad): `expertgranskning_results.application_id/application_error` (068 → 069), se §5.
- Superseded-par (samma tabell) undersökta — alla är kompletterande nycklar, inte dubbletter: `population_members.age` vs `age_bucket`/`lean_key`/`district_key` (båda används för fingerprint), `graph_facts.embedding` vs `embedding_model`, `knowledge_answer_reviews.question` vs `question_key`, m.fl.

## 5. Migrationer — churn och squash-kandidater (inga kan raderas enskilt)

Kedjan är historik och får inte redigeras bakåt; fynden nedan är **kandidater för squash/baseline**, inte för deletion.

| # | Migrationspar | Bevis | Verdict | Förslag |
| --- | --- | --- | --- | --- |
| M1 | `138_graph_fact_revalidation.py` + `139_graph_question_revalidation_work.py` → `142_drop_graph_revalidation_queues.py` | 138:25 skapar `graph_fact_revalidations`; 139:13 skapar `graph_question_revalidation_work`; 142:16-17 droppar båda — bara 3 revisioner senare. 142:s docstring: *"Drop unused …"*. | **A** (ren churn) | Squasha 138/139/142 vid nästa baseline. |
| M2 | `068_word_application_lifecycle.py` → `069_word_actions.py` | 068:23,27 adderar `expertgranskning_results.application_id/application_error`; 069:66-67 droppar dem. | **B** (churn) | Squasha 068/069. |
| M3 | `116_knowledge_claims.py` → `126_knowledge_claim_source_independence.py` | 116:22 skapar `knowledge_claims` med `document_id`/`document_version_id` + 3 index (116:46,50,55); 126:34-35 droppar kolumnerna (index följer med). | **B** (churn) | Squasha 116/126. |
| M4 | `041_panel_sub_questions_and_expert_profiles.py` → `044_panel_expert_profiles_shared_modules.py` | 041:24,54,80 skapar kolumn+index `panel_expert_profiles.module`; 044:45-46 droppar index+kolumn. | **B** (churn) | Squasha 041/044. |
| M5 | `013_catalog_per_configuration.py` | Skapar `catalog_lists_new` (:40), droppar `catalog_lists` (:130), rename → `catalog_lists` (:131); i downgrade skapas `catalog_lists_old` (:152,200-201). | **C** (behåll) | Korrekt slutläge; rör inte. |

Övriga migrationsobservationer:

- **Inga orphan/duplicerade revisioner.** Alla 187 nås från roten; inga okända `down_revision`; inga cykler. Dubbletter i *filnamnsprefix* (`033_*` ×2, `045_*` ×2, `046_*` ×2) är distinkta revisioner före merge 035/048 — **behåll**.
- **Hash-namngiven revision** `e8c2f4a1b6d0_shared_text_chunks.py` (tracked) ligger korrekt mellan `141_canonical_evidence_nature` och `142_drop_graph_revalidation_queues` — kosmetik, inte obsolet.
- **Untracked WIP 167–189 (23 filer):** endast fyra rör schema — 174 skapar `workspace_passage_comments`, 176 skapar `document_ingest_batches`/`_items`, 175 adderar `author_kind`/`expert_id`, 177 adderar `content_sha256` på `stored_objects` + `document_ingest_batch_items`. Alla objekt finns i metadata och nås av kod (WIP-modulerna `document_ingest_batches.py` är också untracked). Resterande är prompt-/datamigrationer. **Behåll — inget är obsolet.** Enda anmärkningen: de är inte git-addade ännu.
- 63 migrationsfiler har inga schemaoperationer i `upgrade()` (prompt-/datamigrationer, varav 4 enbart `execute`). Inget obsolet, men de är kandidater att slås ihop vid baseline.

## 6. Lokal sqlite-drift (inte kodobsolet)

`backend/data/opinionssimulator.db` (untracked, ~52 MB, läst read-only med `mode=ro`):

- `alembic_version` = `105_enable_postgres_rls` → **84 revisioner efter head**.
- 65 tabeller vs 114 i metadata: **49 tabeller saknas** (allt från 106–189); **0 överskottstabeller**.
- **0 kolumner i lokal DB som metadata inte definierar**; 9 tabeller saknar nyare kolumner (t.ex. `research_runtime_needs` 9, `personas` 4, `persona_messages` 3).
- Slutsats: **lokal dev-drift, inte kodobsolet.** Åtgärd: kör `uv run alembic upgrade head` mot lokal fil eller radera/återskapa dev-DB:n. Rapporteras separat enligt uppdraget.

## 7. Falska positiva som INTE får flaggas (verifierade fallgropar)

1. **Dynamiska attributnamn:** `runs.live_progress_{main,a,b}` (`services/run_live_progress.py:15-18`), `kunder`-profilfält (`services/profiles.py:12,21,36-37`). Statisk nollträff ≠ död.
2. **`downgrade()`-droppar:** 117 `drop_table`/48 `drop_column` i downgrade är inte bevis på att objektet är borta — livscykeln är beräknad på `upgrade()` separat. `142` skapar t.ex. båda kö-tabellerna igen i `downgrade()`.
3. **Hjälpfunktioner i migrationer:** `op.create_table` ligger ofta i `_create_workspaces()` (149), `_create_*`, `with op.batch_alter_table(...) as batch/batch_op` — naiv walk av `upgrade()` ger falsk "metadata never created" (4 workspace-tabeller) och missar 80 `batch_op.add_column` + 9 `batch_op.drop_column`.
4. **Rå SQL/DDL utanför metadata:** `mem0_history`, `mem0_messages`, `expert_memories`, `expert_memories_entities` (106) skapas med `op.execute(...)`/`conn.execute(sa.text(...))`; `mem0_history/messages` används via rå SQL i `mem0_postgres_history.py` → behåll.
5. **SQLAlchemy-relationer:** `EvidenceSet.revalidations` (models.py:2086) håller tabellen "vid liv" i metadata utan att någon produktionskod använder den — relationen ska tas bort tillsammans med tabellen, inte räknas som användning.
6. **Alembic-kedjan:** revisioner som bara existerar för att bära historik (merge 035/048, hash-revision e8c2f4a1b6d0) är inte obsoleta.

## 8. Topp-15 — rekommenderad åtgärd (prioritetsordning)

| # | Objekt | Verdict | Rekommenderad åtgärd |
| --- | --- | --- | --- |
| 1 | `evidence_set_revalidations` + `services/knowledge/revalidation.py` + `test_evidence_revalidation.py` + 2 config-fält | **A** | Ny migration efter 189 som droppar tabellen; ta bort modell/relation, modul, test och config-fält. Starkaste drop-kandidaten. |
| 2 | `expert_memories` (pgvector, rå DDL 106) | **B** | Verifiera tomtabell i Supabase; därefter `DROP TABLE IF EXISTS` i postgres-only migration. |
| 3 | `expert_memories_entities` (pgvector, rå DDL 106) | **B** | Som #2 efter verifiering att entitetslänkar migrerats till OverGraph. |
| 4 | `graph_fact_revalidations` | **A** (redan droppad 142) | Ingen åtgärd; dokumentera som avslutat. |
| 5 | `graph_question_revalidation_work` | **A** (redan droppad 142) | Ingen åtgärd. |
| 6 | Migration 138+139+142 | A (churn) | Squash vid baseline; inga separata ändringar. |
| 7 | Migration 068+069 | B (churn) | Squash vid baseline. |
| 8 | Migration 116+126 | B (churn) | Squash vid baseline. |
| 9 | Migration 041+044 | B (churn) | Squash vid baseline. |
| 10 | `configurations.prompts` | C | Behåll; verifiera frontend-editorn innan eventuell pensionering. |
| 11 | `workspace_chats`/`workspace_chat_messages` vs `workspace_conversation_*` | C | Behåll; eventuell konsolidering kräver produktbeslut. |
| 12 | `knowledge_entities`/`knowledge_relationships` vs `graph_nodes`/`graph_facts` | C | Behåll; följ Graph v2-migreringen i docs. |
| 13 | `raw_sources`/`domain_research_results`/`research_claims` vs `evidence_*`/`text_units` | C | Behåll; dual path används i API. |
| 14 | `runs.live_progress_*`, `kunder.organization_*` | C | Behåll — dynamiska referenser (falska positiva). |
| 15 | Lokal sqlite (`backend/data/opinionssimulator.db`) | B (drift) | Uppgradera/återskapa lokal dev-DB (rev 105 → 189). |

## 9. Kvar att verifiera (kräver DB-läsning utanför auditen)

- Radantal i `evidence_set_revalidations` (om >0: arkivera innan drop).
- Om `expert_memories` / `expert_memories_entities` existerar och är tomma i Supabase, samt om data i `expert_memories_entities` redan migrerats till OverGraph.
- Huruvida frontend fortfarande skickar `Configuration.prompts` (avgör om kolumnen kan pensioneras).

**Samordning:** en ny revision (190) kräver uppdatering av hårdkodad head-assertion i `backend/tests/test_alembic_graph_reconcile.py:91`; tabell-drop + modulborttagning påverkar `backend/tests/test_knowledge_tenant_boundary.py` (importerar `EvidenceSetRevalidation`). Koordinera med Audit A (död kod) och Audit C (tester) innan ändring.
