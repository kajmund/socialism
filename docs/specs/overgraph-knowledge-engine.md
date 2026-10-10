# OverGraph – Socialisms kunskapsmotor och persistenta expertminne

**Status:** Godkänd arkitektur  
**Mål:** OverGraph äger den sökbara kunskapsrepresentationen. Mem0 äger expertminnet. Research äger inhämtningen. Jev bedömer semantik.

## 1. Mål

Socialism använder **OverGraph som primär grafmotor** för kunskapslagret och som lagrings- och sökmotor under självhostad mem0.

Bytet är Postgres Graph v2 till OverGraph, inte Neo4j till OverGraph. Ingen Neo4j-integration ska byggas. Ingen migrering av produktionsdata ska skrivas.

Implementationen prioriterar låg latens, hybrid vektorsökning, Jev-styrd traversering, hög ingest-genomströmning och OverGraphs inbyggda algoritmer. Socialism anpassar sin modell till OverGraph, inte tvärtom.

## 2. Ansvar

```text
                       SOCIALISM
                           │
             ┌─────────────┴─────────────┐
             │                           │
        RESEARCH ENGINE              EXPERT CHAT
             │                           │
             │                          MEM0
             │                           │
             ▼                           ▼
      KNOWLEDGE GRAPH              EXPERT MEMORY
             │                           │
             └─────────────┬─────────────┘
                           │
                       OVERGRAPH
                  knowledge/   memory/
                    3072         1536
```

| Äger | Motor | Inte |
| --- | --- | --- |
| TextUnits, faktanoder, entiteter, relationer, embeddings, provenance | Kunskapsgrafen i OverGraph | Postgres-rader för samma text eller vektor |
| Expertminnets livscykel | Självhostad mem0 | En parallell minnessökning i expertchatten |
| Mem0:s persistens och retrieval | OverGraph-minneskatalog | Mem0 Platform Graph Memory |
| Research-jobb, prompter, transaktioner, dokumentmetadata | Postgres | Sökbar källtext |
| Originalfiler | Dokumentlagring | Grafen |

Research läser och skriver sökbar kunskap i OverGraph. Dokumentmetadata stannar i Postgres. Graph v2-SQL används fortfarande av grafens egna enhetstester och av svarsavsnitt som är kopplade till EvidenceSet; det är inte en andra auktoritativ TextUnit-kopia.

## 3. Kataloger och process

OverGraph körs embedded i den backendprocess som utför grafoperationerna. `make start` körs med `RELOAD=0`. En runtime äger två kataloger:

- `OVERGRAPH_DIR/knowledge` — `text-embedding-3-large`, 3072 dimensioner
- `OVERGRAPH_DIR/memory` — `text-embedding-3-small`, 1536 dimensioner

Dense-dimension sätts vid `open()` och kan inte ändras. Därför får kunskap och minne inte dela katalog. Den separata answer-review-processen öppnar inte grafen. Synkrona OverGraph-anrop körs av asyncio-loopen via en worker-tråd. GroupCommit för ingest. `sync()` när en publicerad nod måste vara durable före reuse.

## 4. Grafmodell

OverGraph lagrar vektorer på noder. Kanter har `valid_from` / `valid_to` och `weight`, men ingen stabil `key` och ingen embedding. `edge_uniqueness` gäller `(from, to, label)`.

### Faktanod

Auktoritativt faktum är en nod med `key` = Graph v2 `fact_identity` (scope, ändpunkter, namespaced predicate, context, `occurrence_key`, normaliserad text). Provenance ingår inte. Flera källor kan `SUPPORTS` samma faktanod.

Noden bär text, predicate, occurrence, status och dense-vektor. Strukturella kanter `SUBJECT`, `OBJECT`, `CONTEXT` skrivs i samma `graph_patch`. `core.contradicts` är en kant mellan faktanoder och ogiltigförklarar inte det äldre faktumet. `weight` är OverGraphs rankningssignal, inte identitet.

### TextUnit-nod

Nyckeln är `make_text_unit_id(document_version_id, locator, content_hash)`. Den byts inte ut. Noden bär text, `content_hash`, `document_id`, `document_version_id`, `section_id`, `ordinal`, `locator`, sid- och teckenintervall, `scope_key`, `valid_from`, `valid_to` och `ingested_at`.

`ingested_at` är när occurrence skrevs. Den är inte giltighetstid och inte OverGraphs `created_at`.

Dokumentversionen får en ankarnod utan filbytes. `CONTAINS` går från ankaret till TextUnits. `NEXT` går till nästa `ordinal` i samma version. `SUPPORTS` går från TextUnit till faktanod. Originalfilen och `canonical_documents` stannar i Postgres. `shared_text_chunks` upphör som auktoritativ textkopia. Embedding-cachen får fortfarande återanvända vektorn för samma exakta text.

### Tider

- Giltighet: kantens `valid_from` / `valid_to` (Graph v2 `valid_at` / `invalid_at`)
- Kännedom: property `recorded_at` på provenance
- Källverifiering: property på `SUPPORTS`. Research skriver inte om den.

Research ska inte revalidera. TTL är `knowledge_answer_reviews` och den separata `answer_review_worker`. Grafworkern ingest:ar bara.

## 5. Isolering

`vector_search` filtrerar på nodlabel, inte på godtycklig property. PPR filtrerar inte på tenant. Isolering ska därför sitta i labeln **före** top-k.

Kunskapsnoder bär typ-label (`Fact`, `TextUnit`, `Entity`, `DocumentVersion`) och scope-label (`scope.shared` eller `scope.customer.{id}`). En kunds läsning söker `scope.shared` och eget scope. Kundnoder får referera shared-noder. De får inte ha en kant som PPR kan följa från shared in i en annan kund.

Expertminne: `user_id=kund:{id}`, `agent_id=expert:{key}`. Minnesnoder bär motsvarande labels. Workspace-privata minnen behåller sitt syntetiska `agent_id`. PPR får inte gå mellan experter eller in i kunskapsgrafen. `research_receipt` är en pekare, inte en kopia av evidens.

Fas 2 är inte klar utan ett test som visar att en annan kunds fakta och TextUnits är oåtkomliga i hybrid search, grafscopad sökning, PPR och `traverse`.

## 6. Retrieval

Identifierare och frågeberoenden slås upp först. Därefter:

1. Hybrid eller dense search över `Fact` och `TextUnit` i tillåtna scope-labels
2. Grafscopad vektorsökning från seed-noder
3. Personalized PageRank (`approx`) som relevanssignal
4. `top_k_neighbors` för att begränsa Jev-kandidater
5. Batchad NOUL
6. Budgeterad traversal, inklusive `SUPPORTS` och `NEXT`

En TextUnit utan färdigt faktum är ett giltigt träff. Sparse-vektorer kräver en encoder som Socialism inte har. Paragrafnummer och dokumentidentiteter slås upp via identifierare. Shortest path, connected components, GQL och decay byggs när ett konkret anrop behöver dem.

Python reciprocal rank fusion i Graph v2 ersätts. OverGraphs fusion används när både dense och sparse finns.

## 7. Skrivningar

| Arbetslast | Strategi |
| --- | --- |
| Normal ingest | `batch_upsert` / `graph_patch` |
| Stor initial ingest | `ingest_mode()` / `end_ingest()` |
| Ogiltigförklaring | `invalidate_edge` med strukturella guarder |
| Ingest-hållbarhet | GroupCommit |
| Publicerad reuse | `sync()` |

Embeddings och Jev körs utan öppen Postgres- eller OverGraph-skrivtransaktion. Exact identity kontrolleras före embedding. Legal write-back stannar i Postgres-outboxen och skrivs till OverGraph efteråt.

Två Jev-roller:

- Ingest: SAME / DISTINCT / CONTRADICTS när exakt identitet inte räcker
- Traversering: NOUL i batch. Deterministiskt bortfiltrerade relationer skickas inte dit

## 8. Mem0

Expertminnet är självhostad `mem0ai==2.0.20`. Expertchatten anropar mem0. Mem0 anropar OverGraph via en `VectorStoreBase`-adapter. Inget nytt minnesflöde byggs bredvid.

Adaptern hakas in som historikadaptern: `VectorStoreFactory` och `VectorStoreConfig` saknar `register` för OverGraph, så Socialism patchar in providern `overgraph`. Mem0 anropar insert, search, update och delete. `search` får göra grafexpansion internt och returnerar mem0:s vanliga träfflista.

Mem0 skickar `text-embedding-3-small`. Adaptern uppfinner inte en sparse-encoder. Entitetslänkar som idag ligger i `expert_memories_entities` blir noder och kanter i minneskatalogen. Delete tar bort nod, kanter och vektorindex.

[Mem0 Platform Graph Memory](https://docs.mem0.ai/platform/features/graph-memory) används inte. Det gamla `graph_store`-gränssnittet är borttaget där och finns inte i det pinnade OSS-paketet. OverGraphs `prune` får inte radera minnen som mem0 fortfarande äger.

## 9. Faser

1. Inventering — klar i den här specen
2. Kunskapsgraf: TextUnit-noder, faktanoder, `CONTAINS` / `NEXT` / `SUPPORTS`, scope-test, två kataloger, processägare
3. Hybrid search, grafscope, PPR, top-k över fakta och TextUnits
4. Adaptiv Jev-traversering med batchad NOUL
5. Ingest via OverGraphs batch-API utan LLM i transaktion
6. Mem0 `VectorStoreBase`-adapter
7. Benchmark mot `36 § avtalslagen` och reuse-kontraktet; ta bort ersatt SQL när svarsavsnitt och legal ingest inte längre behöver Graph v2-tabellerna

## 10. Acceptance

1. OverGraph är den sökbara kunskapsmotorn
2. Ingen Neo4j-integration
3. Faktaidentitet, provenance och temporalitet från Graph v2 fungerar
4. TextUnits är noder; research hämtar inte stycket i Postgres efter graffrågan
5. Dense retrieval används; hybrid när sparse finns
6. Graph-scoped search, PPR och top-k används
7. Jev bedömer flera traverseringskandidater i batch
8. Ingest håller inte databastransaktion över LLM
9. Mem0 äger expertminnet; OverGraph lagrar och hämtar
10. Tenant-, användar- och expertisolering gäller före top-k
11. Minnesradering tar bort relationer och index
12. Tester täcker ingest, retrieval, traversering, isolering och minne
