# 42 – Riktig korpusingest och Tabular Review-mätharness

Type: task
Status: claimed
Blocked by: 41

## Question

Gör ticket 40 körbar på riktiga avtal:

- Ingessa den riktiga ~200-avtalskorpusen i Postgres + Overgraph med samma
  dokument-/TextUnit-modell som produktionen.
- Bygg harness som skapar review, kör kall/varm tabell och mäter tid till första
  rad, tid till komplett tabell, backendtid, cache hit rate, Recall@1/3/5,
  abstention, låsta celler och återkallelse.
- Mät UI-prestanda separat från backend; låg score ska vara `Ingen träff`.
- Inga Jev/narrativa LLM-anrop i mätningen; inga ändringar i research/SWE.

Därefter kan ticket 40 köras och ticket 38 följa.

## Ingångsvärde 2026-10-24

Granskningskandidaterna i `clause_review_candidates_v1.json` (35 avtal, 140
kort, anchor/test-split) kan användas för att prioritera ingest och adminkö.
Ticket 42 ansvarar för: ingest av den mindre korpusen, adminflöde som skapar
verifierade kort, samt prestandamätning (kall/varm, tid till första rad,
komplett tabell, cache, låsta celler, återkallelse). Ingen kvalitetsmätning
förrän ticket 41 är fryst.

## Påbörjat 2026-10-24: ingest + backendprestanda

PR #430 (`ticket40-tabular-perf`) innehåller en körbar harness som:
- ingestar 35 syntetiska avtal (2 377 TextUnits) i temp-SQLite + Overgraph med
  riktiga OpenAI-embeddings;
- bygger syntetiska provisoriska ankare (performance-only, ej verifierade);
- mäter kall fyllning, varm fyllning, ny kolumn och en första-rads-proxy.

Lokala resultat: ingest ~9,2 s; kall fyllning ~11,5 s; varm ~0,64 s; ny fjärde
kolumn ~4,9 s; första-rads-proxy ~0,04 s; 9 508 cacherader.

Detta är **inte** kvalitetsmätning och inte UI-tid. Kvar för ticket 42:
adminflödet på de ingästa avtalen, UI-paint/scroll/PDF-positioner, samt
separat loggning av varför en cell är no-hit (låg similarity, saknad embedding,
återkallat ankare, tekniskt fel). Därefter kan ticket 40/43 köras.

## Profilering 2026-10-24 (PR #430)

Fasprofiler på 35 avtal / 2 377 TextUnits / 4 kolumner:

| Fas | Kall | Varm | Ny kolumn |
| --- | ---: | ---: | ---: |
| load_inputs | 0,01 s | 0,01 s | 0,01 s |
| load_anchors (Overgraph) | 0,002 s | 0,002 s | 0,002 s |
| load_units (Overgraph) | 0,26 s | 0,21 s | 0,20 s |
| cache_keys + lookup | 0,03 s | 0,07 s | 0,20 s |
| score (cosine) | 3,52 s | 0,03 s | 1,17 s |
| bygg cache-rader | 3,28 s | 0,01 s | 1,20 s |
| persist (celler + 9 508 cacherader) | 4,95 s | 0,29 s | 1,67 s |
| **totalt** | **12,06 s** | **0,62 s** | **4,45 s** |

Slutsats: Overgraph-läsning är billig. Den kalla tiden och ny-kolumn-tiden
domineras av den fullständiga TextUnit×kolumn-cachegridden (9 508 rader):
cosine, objektbygge och persist. Batchning av cache-skrivningar hjälpte inte
materiellt. Nästa optimering bör därför vara cachegranularitet (endast
toppkandidater per avtal/kategori eller lat cache) och att återanvända
oförändrade kolumner — inte mer cosine-optimering. Det kräver kvalitetsmätning
innan den antas vara likvärdig.

No-hit-diagnostik är klar i PR #431: cellen får `below_threshold`,
`no_active_anchors`, `no_candidates` eller `abstain_margin`; saknad embedding
är fortfarande ett tekniskt fel, inte `no_hit`. Kvar för ticket 42: adminflöde
på ingästa avtal, UI-paint, scroll/sortering och PDF-positioner. PR #430 är
fortsatt experimentell.
