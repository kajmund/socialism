# Så fungerar forsknings‑subsystemet i **Socialism**

Detta dokument ger en översikt av hur forsknings‑motor​n (research subsystem) är byggd och hur data flödar från en körning (`ExecutionAttempt`) till ett fryst `EvidenceSet`. Alla huvudkomponenter och deras samspel beskrivs, samt viktiga kantfall som stop‑ och fel‑scenarier.

---

## 1. Grundbegrepp

| Begrepp | Beskrivning |
|---------|-------------|
| **ExecutionAttempt** | En körning av en användar‑/system‑begäran. En attempt har en unik `attempt_id` och är den övergripande enheten som driver forsknings‑loopen. |
| **EvidenceSet** | Samling av all bevis (artiklar, domar, etc.) som hämtas för en attempt. När loopen är färdig “fryses” (`freeze`) den så att inga fler bevis läggs till. |
| **ResearchNeed** | En specifik fråga eller problem som måste besvaras. Varje need har ett `question`, en `source_type`‑lista och en `origin` (t.ex. *main*, *follow‑up*). |
| **ResearchPlan** | En validerad plan som listar alla `ResearchNeed`s som ska bearbetas. En tom plan är ogiltig – den måste innehålla minst en need. |
| **ResearchContext** | Kontext‑objekt som bär bland annat ärendets (`case_id`) och eventuella extra metadata. |
| **ResearchRouter** | Ansvarar för att matcha en `ResearchNeed` mot lämpliga kunskaps‑leverantörer (providers). |

---

## 2. Komponent‑översikt

### 2.1 `execution.py` – Huvud‑orchestrering
*Fil:* `backend/app/services/research/execution.py` (början linje 1‑7)

Denna fil implementerar **attempt‑scoped** forskning:
* Initierar en `ResearchPlan` från en snapshot (`research_plan_from_snapshot`).
* Kör en **loop** över “waves” av behov, där varje wave begränsas av `research_need_concurrency`.
* Hanterar persistens av bevis via `add_evidence_items`, `attach_evidence_set` osv.
* När alla behov är klara eller ett stop‑skäl inträffar kallas `_freeze_ready_attempt` för att frysa `EvidenceSet`.

### 2.2 `router.py` – Deterministisk provider‑val
*Fil:* `backend/app/services/research/router.py` (linje 1‑40)

`ResearchRouter` får en `ResearchNeed` och:
1. Bygger en lista av **ProviderCandidate**‑objekt med hjälp av `constraints_from_need`.
2. Filtrerar kandidater med `filter_source_types_for_scope`.
3. Sorterar och rangordnar dem via `rank_provider_candidates`.
4. Hämtar bevis genom att anropa `source.research(need, context)`.
5. På fel returneras en `ResearchEvidence` med status *error* eller *not_found* (funktioner `_error_evidence` och `_not_found_evidence`).

Det är **deterministiskt** – ingen LLM eller tidig exit på “träff”. Alla fel omvandlas till strukturerade `ResearchEvidence`‑objekt.

### 2.3 `registry.py` – Capability‑register
*Fil:* `backend/app/services/research/registry.py` (linje 39‑66)

Registrerar kunskaps‑leverantörer baserat på deras **capability descriptors**. Standard‑sättet (`standard_capability_descriptors`) sammansätter:
* Lagen‑nu‑capabilities (`lagen_nu_capability_descriptors`)
* Supabase adapters för *case*, *customer* och *domain* kunskap (`knowledge_adapter_descriptor`).
Detta ger ett **fast kontrakt** för vilka **evidence‑natures** som kan levereras (`production_registered_source_types`).

### 2.4 `loop_control.py` – Loop‑styren och beslutslogik
*Fil:* `backend/app/services/research/loop_control.py` (linje 55‑63)

`ResearchLoopConfig` samlar alla beroenden som behövs för en loop (session‑factory, router, kontext, normalizer, etc.).

Funktionen `stop_and_freeze` tar hand om:
* Sättning av loop‑tillstånd (`set_research_loop_state`).
* Valfri efter‑tillstånd‑callback (`after_state`).
* Kallar `_freeze_ready_attempt` för att låsa `EvidenceSet` (linje 100‑102).

Den stora loopen (snarare i `execution.py`) använder `decide_after_assessment` och `decide_after_completeness` (se `loop_decision.py`) för att avgöra om loopen ska **fortsätta**, **planera fler behov**, eller **stoppa**.

### 2.5 `loop_decision.py` – Besluts‑logik (ren, ingen I/O)
*Fil:* `backend/app/services/research/loop_decision.py` (linje 12‑62)

Definierar `LoopDecision` med handlingar:
| Action | När den inträffar |
|--------|-------------------|
| `stop` | Slut på loopen – kräver `stop_reason`. |
| `review_completeness` | Efter en lokal bedömning men innan global granskning. |
| `plan_global` | Efter en global gransknings‑pass, men innan max‑pass eller max‑waves nås. |
| `plan_follow_up` | När lokal bedömning är *insufficient* och max‑follow‑up‑waves ej nåtts. |

Besluten bygger på parametrar såsom `assessment_result`, `existing_completeness_passes`, `wave` och konfigurations‑gränser (`max_follow_up_waves`, `max_completeness_passes`).

### 2.6 `assessment.py` – Lokal evidens‑sufficiens
*Fil:* `backend/app/services/research/assessment.py` (linje 1‑80)

`ResearchAssessor` (konkret implementation i `app/services/research/assessment.py`, t.ex. `ProgrammaticResearchAssessor`) tar en lista av `AssessableEvidence` (persisted evidens) och:
* Anropar LLM‑modell för att klassificera varje need som **sufficient** eller **insufficient**.
* Returnerar `ResearchAssessmentDraft` med `assessment_result` (`"sufficient"` / `"insufficient"`).
* Eventuella fel (modell‑ eller parsing‑fel) lyfts som `ResearchAssessmentError`.

### 2.7 `completeness.py` – Global completeness‑granskning
*Fil:* `backend/app/services/research/completeness.py` (linje 1‑60)

`ResearchCompletenessReviewer` analyserar hela **ResearchPlan** och identifierar:
* **MaterialMissingQuestion** – frågor som saknas i plan‑snapshoten.
* **capability gaps** – när inga leverantörer kan tillhandahålla önskad kunskap.
Resultatet (`CompletenessResult`) är antingen `"complete"` eller `"incomplete"`. Om det är `"incomplete"` planeras nya globala behov (`plan_global`).

### 2.8 `followup.py` – Planering av uppföljnings‑behov
*Fil:* `backend/app/services/research/followup.py` (linje 1‑60)

`FollowUpResearchPlanner` (eller `NoOpFollowUpPlanner` när ingen nyhet krävs) bygger **FollowUpNeedDrafts** baserat på:
* Otillräcklig evidens från `ResearchAssessment`.
* Materiala frågor från `ResearchCompletenessReviewer`.
Varje follow‑up‑draft har fält som `question`, `source_types`, `domains`, `capabilities` och en unik `proposed_id`.

### 2.9 `research_worker.py` – Bakgrunds‑worker som tar claim och kör loopen
*Fil:* `backend/app/services/research_worker.py` (linje 1‑80)

* **`enqueue_research(attempt_id)`** lägger en attempt‑id i en kö. En bakgrunds‑task (`_schedule_hook`) startar sedan `execute_attempt_research`.
* **`execute_attempt_research`** (i `app/services/research/execution.py`) kör hela loopen med all logik ovan.
* Vid fel kallas `fail_attempt`, `fail_need_execution`, `fail_evidence_set` etc., vilket markerar attempt‑ och evidens‑set som *failed* i databasen.

---

## 3. Dataflöde – Från attempt till fryst EvidenceSet
```
+-------------------+      +----------------------+      +--------------------+
| ExecutionAttempt  | ---> | ResearchExecution   | ---> | EvidenceSet (frozen)|
+-------------------+      +----------------------+      +--------------------+
        |                         |   ^                         |
        |                         |   |                         |
        |   (plan)                |   | (needs)                 |
        v                         v   |                         |
  ResearchPlan  <---  LoopControl <---  ResearchNeed(s)         |
        |                         |   |                         |
        |   (router)              |   | (provider)               |
        v                         v   v                         |
  ResearchRouter (deterministic)  Provider(s) --------------> EvidenceSetItem
```
1. **Start** – `research_worker.enqueue_research` hämtar en `ExecutionAttempt`.
2. **Planering** – `research_plan_from_snapshot` skapar ett `ResearchPlan`.
3. **Loop** – `execution.py` kör `execute_attempt_research`:
   * Skapar initiala `ResearchNeedExecution`‑rader (`seed_need_executions`).
   * För varje **wave**:
     * Hämtar behov (`list_runtime_needs`), normaliserar dem (`ResearchNeedNormalizer`), och bestämmer leverantörer via `ResearchRouter`.
     * Kör parallella provider‑anrop (begränsad av `research_need_concurrency`).
     * Persisterar bevis (`add_evidence_items`).
     * Bedömer lokalt (`ResearchAssessor`) → `assessment_result`.
     * Beslutar nästa steg med `decide_after_assessment`.
4. **Global granskning** – Om lokala behov är tillräckliga men plan är ofullständig körs `ResearchCompletenessReviewer`.
5. **Follow‑up** – Vid `insufficient` eller `incomplete` planeras nya behov (`FollowUpResearchPlanner`).
6. **Stop‑skäl** – När `LoopDecision` är `stop`, anropas `stop_and_freeze` → `set_research_loop_state` och `_freeze_ready_attempt`.
7. **Frysning** – `EvidenceSet` får status *frozen*; inget mer kan läggas till.

Resultatet (`AttemptResearchResult`) innehåller räknare för **found**, **not‑found** och **error** bevis, samt `evidence_set_id`.

---

## 4. Stopp‑ och fel‑hantering

| Scenario | Vad som händer |
|----------|----------------|
| **Lokal bedömning *sufficient*** och max antal global‑pass nått | `LoopDecision(action="stop", stop_reason="max_completeness_passes")`. |
| **Global granskning *complete*** | `LoopDecision(action="stop", stop_reason="sufficient")`. |
| **Max antal follow‑up‑waves nått** | `LoopDecision(action="stop", stop_reason="max_iterations")`. |
| **Provider‑fel** (t.ex. timeout, `LagenNuSelectionError`) | Skapas en `ResearchEvidence` med `status="error"` via `_error_evidence`. |
| **Ingen leverantör för önskad kunskap** | `ResearchEvidence` med `status="not_found"` lagras. |
| **Kritisk kod‑ eller modell‑fel** (`ResearchAssessmentError`, `ResearchCompletenessError`, etc.) | Orkestreringen fångar undantaget, markerar attempt som *failed* (`fail_attempt`) och avbryter loopen. |
| **Database‑connection‑policy** – anslutning ska alltid släppas innan externa anrop sker. Detta följs i hela koden genom att materialisera data innan `await`‑anrop mot providers eller LLM‑modeller. |

---

## 5. Edge Cases & Specifika Kontroller

1. **Capability‑gap** – Om ingen provider kan leverera en begärd `source_type` registreras en `capability_unavailable`‑händelse (`emit_capability_unavailable`). Detta kan trigga en global planering av nya behov.
2. **Case‑krav** – Vissa providers kräver ett `case_id`; `router._case_required` hanterar detta och kan avvisa en need utan case.
3. **Racing / Concurrency** – `research_need_concurrency`, `research_source_concurrency` och `research_document_concurrency` begränsar parallellism så att databasen inte överbelastas.
4. **Loop‑abort** – `require_stop_reason` (`followup.py`) säkerställer att alla `stop`‑beslut har en tydlig orsak.
5. **Observability** – Kontextvariabler (`bind_log_context`, `bind_research_stats`) och emitter‑funktioner (`emit_need_queued`, `emit_assessment_persisted`) möjliggör detaljerad loggning utan att hålla öppna DB‑transaktioner. 

---

## 6. Testning & Säkerställning

- **Enhetstester** för varje modul finns under `tests/` och validerar t.ex. `router._error_evidence`, `loop_decision.decide_*`, och `assessment.review_excerpt`.
- **Integrationstest** – `tests/integration/test_research_flow.py` kör hela loopen med en in‑memory SQLite‑session och simulerade providers.
- **Databas‑policy** – Alla testfall använder `set_research_session_factory` för att injicera en test‑session, så att DB‑anslutningar alltid släpps innan externa anrop.

---

## 7. Sammanfattning

Forskning‑subsystemet är ett **asynkront, modulariserat** arbete som:
1. **Initierar** en plan från en snapshot.
2. **Kör** en begränsad, våg‑baserad loop av research‑needs.
3. **Routar** varje need till lämpliga kunskaps‑leverantörer utan LLM‑baserad fallback.
4. **Bedömer** lokalt (sufficiency) och globalt (completeness).
5. **Planerar** uppföljnings‑needs när bevis saknas eller nya frågor uppstår.
6. **Stoppar** och **fryser** när mål är uppfyllda eller max‑gränser nås.

Denna arkitektur följer strikt **database‑connection‑release‑policy**, har tydliga stopp‑skäl och är starkt observerad via logg‑ och statistik‑hooks, vilket möjliggör pålitlig körning både i test‑ och produktionsmiljöer.
