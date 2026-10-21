# Inventering: Evidensförankrad dokumentidentifiering och Jev-verifiering

Integrationsspec §4 + leveranspunkt 6. Detta dokument kartlägger vad som redan
finns i kodbasen, vad experimenten bevisade, och var integrationssömmarna går.
Det är underlaget för den fasade implementationen — inte själva implementationen.

## 1. Två kodbaser som ska mötas

### A. Prototypen (`experiments/overgraph_ingest/`)

Isolerat experimentpaket. Alla frysta resultat är producerade här.

| Komponent | Roll i specen |
|---|---|
| `retrieval/document_properties.py` | Deterministisk discovery (taxonomi + lexikon + struktur), `PropertyClass`, `DocumentProperty`, `extract_document_properties`, `ranked_documents`, `lookup_documents` |
| `retrieval_gold/document_properties/taxonomy-v1.json` | Fryst taxonomi (9 egenskaper, positiva/negativa formuleringar, composites) |
| `retrieval_gold/document_properties/gold-mapping-v1.json` | Fryst gold → egenskapsmappning |
| `retrieval/jev_property_verify.py` | Jev-verifiering (SUPPORTED/UNSUPPORTED/UNDECIDED, `validate_source`) |
| `retrieval/jev_presentation_v1.py` | Presentationsfixen: kandidatklausuler som primär evidens (`evidence_clauses`) |
| `retrieval/jev_end_to_end.py` / `jev_local_query_abc.py` / `jev_validation_v1.py` | Pipeline, A/B/C-frågejämförelse, bred validering |
| `doctags/source.py` | `validate_source` (excerpt → TextUnit, exakt delsträng) |
| `doctype/`, `doctags/` | Dokumenttyp-/tagklassificering (angränsande, ej kärnan här) |
| `coverage/` (`proof_gate`, `proof_logic`, `predicate`) | Bevislogik för passagetäckning (angränsande) |

Frysta baselines som är jämförelseunderlag (ej produktionsgarantier):
`baselines/phase2-document-properties-v1.json`,
`phase2-jev-property-verification-v1.json`, `phase2-jev-end-to-end-v1.json`,
`phase2-jev-local-query-abc-v1.json`, `phase2-jev-presentation-v1.json`,
`phase2-jev-validation-v1.json`.

### B. Produktionen (`backend/`)

Mogen dokument-/expert-/workspace-plattform. Nyckelkomponenter att återanvända:

| Komponent | Roll |
|---|---|
| `services/document_ingest_*`, `document_upload.py`, `document_item_index.py` | Dokumentintag → `StoredObject` + `TextUnitRecord` |
| `services/document_knowledge.py`, `knowledge/persistence.py` (`current_text_units`, `supporting_text_unit_ids`) | TextUnit-uppslag och källförankring |
| `services/document_item_grounding.py` | Validerar käll-länkar vid mutation (mönster för `validate_source` i produktion) |
| `services/knowledge/` (`claims.py`, `relationships.py`, `claim_store.py`, `extractors.py`) | Befintligt claims-/relations-/verifieringsramverk |
| `services/overgraph/` (`model.py`, `write.py`, `retrieval.py`, `browse.py`, `catalogs.py`) | OverGraph (mem0-baserad, katalogerna `knowledge` + `memory`) |
| `api/overgraph.py` | Admin-läs-API för OverGraph-katalogerna |
| `services/expert_tools.py`, `expert_async_tools.py`, `expert_tool_run.py` | Befintlig verktygsrouting / exekvering |
| `services/legal_research_result.py` (`validate_source`), `schemas/domain.py` | Evidensvalidering (produktion) |
| `backend/app/jev/system.py` | Jev-adapter i produktion |
| `services/latency_stats.py`, `job_events.py` | Mätning / jobb-event |

## 2. Vad experimenten bevisade (fryst)

| Mått | Värde |
|---|---|
| Property recall (makro, discovery) | 97,5 % |
| Discovery-modellanrop | 0 |
| Gold-positiva verifierade | 116/116 (98 direkt, 18 via lokal dense) |
| Återhämtade efter lokal dense | 51 |
| Jev-anrop per dokumentegenskap | 1,34 |
| Latens p50 / p95 (kedjan) | 258 ms / 560 ms |

Kärninsikten: deterministisk discovery behåller recall; Jev höjer precision utan
att avvisa korrekta dokument, **förutsatt att kompletterande TextUnits
presenteras som primär evidens** (`evidence_clauses`), inte som excerptval.
`UNSUPPORTED` betyder "evidensen stödde inte", aldrig "egenskapen saknas".

## 3. Integrationssömmar (experiment → produktion)

| Spec-krav | Experimentkälla | Produktionsmål |
|---|---|---|
| Deterministisk discovery | `document_properties.extract_document_properties` | Kör mot `TextUnitRecord` + struktur i produktion |
| Taxonomi | `taxonomy-v1.json` (fryst) | Importeras oförändrad (ny version efter mänsklig granskning) |
| Jev-verifiering | `jev_property_verify._verify` / `jev_presentation_v1._verify_present` | `backend/app/jev/` + `expert_tools` |
| Källförankring | `doctags/source.validate_source` | `document_item_grounding.validated_unit_ids` / `supporting_text_unit_ids` |
| Lokal dense | `jev_end_to_end._dense_top` (gold.query) | `services/workspace/search.py` + dense i produktion; frågetext från användarfråga, ej gold |
| Dokumentegenskapsregister | `document_properties` (in-memory) | OverGraph (`write.py`) eller `claims`/`relationships` i `services/knowledge/` |
| Property lookup + paginering | `document_properties.lookup_documents` | Nytt API + `services/document_item_index.py` |
| Asynkron verifieringskö | `jev_validation` (loop) | `expert_async_tools` / `job_events` / befintlig kö |

## 4. Kända beslutspunkter (måste avgöras i fas 1)

1. **Var lagras egenskaperna?** Produktionens OverGraph är mem0-baserad
   (`knowledge`/`memory`), medan experimentet använde en TextUnit/Structure-graf.
   Alternativ: (a) `services/knowledge/` claims/relationships, (b) OverGraph
   `write.py`, (c) en ny `DocumentProperty`-tabell vid sidan av
   `DocumentKnowledgeItem`. Specen säger "ingen ny separat databas" och
   "Overgraph som kunskapslager" → lutar åt (b) eller (a).
2. **Vilken frågetext för lokal dense?** Experimentet använde `gold.query`.
   Specen kräver användarens ursprungliga fråga i produktion.
3. **Verifieringskontraktets utdata** (decision/source/reason_code) ska mappa
   mot produktionens befintliga Jev-svarsschema (`backend/app/jev/system.py`).

## 5. Fasplan

| Fas | Innehåll | Leverans |
|---|---|---|
| **0 — Inventering** | Detta dokument + bekräftelse av §4-besluten | ✔ (denna) |
| **1 — Vertikal skiva** | Deterministisk discovery + Jev (presentationsfix) + lokal dense + register på ett dokumentflöde, med `validate_source`-förankring | End-to-end på ett dokument, tester |
| **2 — Register + lookup** | Egenskapspersistens i OverGraph/claims, `class_id`/värde/polaritet, dokument-/tenant-scope, paginerad lookup utan topp-k | API + tester |
| **3 — Asynkron kö** | Inkrementell verifieringskö (concurrency, backpressure, avbryt, deduplicering, versionslåsning) | Kö + status |
| **4 — Expertverktyg** | Routing så att experten kan begära inventering utan egen loop; presentation i chatt | Verktyg + chatt |
| **5 — Regression + prestanda** | Återanvänd frysta fall (116 positiva, 111 misstänkta, 4 avvikelser, 3 presentation-missar) + nya dokument; mät på nytt | Regressionsrapport |

## 6. Återanvändning och städning (preliminärt)

- **Återanvänd:** `validate_source`-mönstret, `supporting_text_unit_ids`,
  `expert_tools`-routing, `expert_async_tools`-kö, `overgraph/write.py`,
  `document_item_index.py`, `latency_stats.py`.
- **Städa (först när beroenden/tester är flyttade):** experiment-CLI-flaggorna
  `--document-properties`, `--jev-property-verification`, `--jev-end-to-end`,
  `--jev-local-abc`, `--jev-presentation`, `--jev-validation` konsolideras till
  en integrerad pipeline och tas bort ur `ingest.py` efter att produktionen
  täcker dem. Ingenten tas bort innan tester flyttats.
