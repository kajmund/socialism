# Fas A1: auktoritativ answer reuse via Owner

Status: implementerad och verifierad i PR #432. Detta är första steget i Fas A;
retrieval, ranking och researchbeslut är oförändrade och ligger kvar utanför
Owner.

## Vad som migrerats

`lookup_answers` i `backend/app/services/research/answer_graph.py` använder nu
owner-läsvägen när en owner-klient är konfigurerad:

| Uppslag | Owner-funktion |
| --- | --- |
| question alias → question node | `find_question_via_owner` (batchad `read` för alla synliga scopes) |
| answer facts via `SUBJECT`-kanter | `answer_facts_via_owner` (`neighbors`, status/validity före limit) |
| answer entity attributes | `entity_attributes_via_owner` (`read`) |
| dependencies current check | `current_facts_via_owner` (en batchad `read` för alla fact-ids) |

`require_knowledge()` anropas inte i owner-läget. Utan owner konfigurerad behålls
den tidigare direkta katalogvägen oförändrad (tester/offline). Ingen ny
retrievalalgoritm, ingen ändrad ranking, inga nya SQL-lager.

## Mätt datatransport (A2)

`backend/scripts/benchmark_answer_reuse.py`, riktig owner-process/socket:

| Evidens i svaret | Owner-reads | Socket-bytes | Median-latens |
| --- | ---: | ---: | ---: |
| 1 | 4 | 3,2 KB | 1,85 ms |
| 10 | 4 | 8,5 KB | 1,91 ms |
| 100 | 4 | 62 KB | 3,01 ms |

Läsningen är alltså fyra bounded RPC oavsett evidensmängd. Bytes skalar med
svarets `basis`: answer-nodens `attributes_json` innehåller hela den frysta
evidenslistan, som returneras när entity-attributen läses. Det är medvetet – hela
answer-episoden måste bevaras – men det är den punkt som ska bevakas om
evidensmängderna växer. Ingen full graph eller embeddings transporteras.

## Verifiering

- `backend/tests/test_owner_answer_reuse.py`: publicerar via produktionens
  `publish_answer_via_owner`, monkeypatchar `require_knowledge` att kasta fel och
  verifierar att `lookup_answers` ändå hittar svaret via owner, med korrekt
  `answer_fact_id` och `reuse.evidence_ref`.
- Multiprocess-harnessen: backend A publicerar ett fryst svar via produktionens
  owner-writer (test-endpoint), backend B hittar och återanvänder det genom sin
  egen HTTP-lookup. B:s guard loggar 0 lokala knowledge-öppningar.
- `tests/research_reuse` och `test_overgraph_owner_answer_publish` är gröna;
  direct/owner-pariteten för publicering är oförändrad.

Test-endpointen publicerar en redan fryst answer; den går inte genom hela
researchkörningens SQL/LLM-väg. Själva skrivningen är däremot produktionens
`publish_answer_via_owner`, och läsningen är produktionens `lookup_answers`.

## Kvar i Fas A

- `lookup_graph_evidence`/graph reuse och hybrid retrieval (`lookup_candidates`,
  vector search) läser fortfarande en lokal katalog i icke-owner-läge och är
  **inte** migrerade. I owner mode failar de closed.
- Ingen ändring av retrievalkvalitet är gjord eller påstådd; A1 rör bara själva
  grafuppslagen för kända answer-episoder.
- Nästa steg är A2:s återstående retrieval/rankingmätning när graph reuse
  migreras, samt Tantivy-frågan med tre mätta alternativ.
