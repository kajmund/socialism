# 44 – Isolerat A/B/C-cacheexperiment för Tabular Review

Type: task
Status: claimed

## Question

Jämför full cachegrid (A), Top-K-persistens med samma scoring (B) och
vektoriserad scoring + Top-K (C) på 35 avtal / 2 377 TextUnits / 4 kategorier.

- Samma embeddings, ankare, dokument, trösklar och kandidatgräns i alla armar.
- Identiska Top-1/3/5 med stabil tie-breaking; scores inom tolerans; negativa
  ankare, abstention, revocation och låsta celler oförändrade.
- Mät kall, varm, ny kolumn, score/objektbygge/persist/Overgraph och antal
  persistenta rader; mål kall <2 s, varm ≤0,62 s, ny kolumn <1 s (hypoteser).
- Skilj embeddingcache (Overgraph, content-addressed) från resultatcache
  (Top-K per dokumentversion/kategori/AnchorSet-revision); ingen ny Redis/SQL/
  vektordatabas.
- Sänkt tröskel får inte använda en gammal Top-5 som hela kandidatrymden.

Protokoll: `docs/architecture/tabular-review-cache-experiment.md`. PR #430 är
baseline och förblir experimentell. Ingen produktionsändring förrän A/B/C är
identiska och ticket 42:s admin/UI/no-hit är klart.

## Första A/B/C/D-körning 2026-10-24 (PR #430)

35 avtal / 2 377 TextUnits / 4 kolumner, 2 repetitioner, median (p95):

| Arm | Kall | Varm | Ny kolumn | Score-cacherader |
| --- | ---: | ---: | ---: | ---: |
| A full grid | 8,43 s (28,8) | 0,85 s (0,89) | 4,53 s (4,97) | 9 508 |
| B Top-K, loop | 4,69 s (4,85) | 0,014 s (0,015) | 1,22 s (1,25) | 0 |
| C vektoriserad + Top-K | 1,05 s (1,09) | 0,014 s (0,017) | 0,36 s (0,43) | 0 |
| D vektoriserad, ingen similarity-cache | 1,02 s (1,03) | 1,09 s (1,10) | 0,31 s (0,32) | 0 |

Top-5-paritet: 140/140 celler för alla armar. Resultatkandidater ~700 per arm.

Slutsats: C/D når kall <2 s och ny kolumn <1 s; B visar att Top-K-persistens
ensam halverar men inte når målet. D (explorativ) visar att den dyra delen är
att skriva/underhålla similarity-cachen, inte att räkna om vektoriserad cosine:
warm utan cache är ~1,09 s men kall ~1,02 s. Nästa: revocation-paritet och
admin/UI/PDF; därefter adoptionsbeslut. A:s p95 är hög (varians i SQLite).

## Viktig upptäckt om C:s varma cache 2026-10-24

C:s 14 ms är **inte** en begränsad minnescache. Prototypen persisterar
Top-K-resultaten som vanliga `TabularReviewCell`/`TabularReviewCandidate`-rader
och varmkörningen läser dem utan att kontrollera om dokument, AnchorSet-revision
eller tröskel har ändrats. Det gör att siffran inte får användas som
adoptionsbevis: en gammal cell kan återanvändas efter återkallat ankare eller
uppdaterat dokument.

Därför är C ännu inte en produktionskandidat. Nästa steg är ticket 45:
resultatcache-nyckel/revision, invalidering och revocation-paritet, inklusive
processomstart och två workers. D är fortfarande enkel fallback som räknar om.
