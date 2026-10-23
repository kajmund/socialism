# Adoptionsbeslut: hybrid kandidatgenerering

Type: grilling
Status: resolved
Blocked by: 24

## Question

Ska hybrid (deterministisk ∪ embeddings) bli standard för kandidatgenerering i
experimentarmarna, trots att det förregistrerade kriteriet "Jev-anrop inte
högre" fallerar med +0,7 %?

Underlag B4b:

- 22/26 rätt mot 16/26.
- 0 false-sufficient mot 6.
- Candidate Recall 14 mot 8; Recall@40 12 mot 6.
- 2 336 mot 2 320 Jev-anrop (+16); latens 185 s mot 161 s.
- Oförändrad coverage (22/22), oförändrade compatible-false-insufficient.
- Ingen produktionsändring gjord.

## Att besluta

- **Adoptera hybrid som experimentstandard** med dokumenterad tolerans för
  marginellt fler Jev-anrop, och lås kriteriet "inga nya false-sufficient,
  ingen försämrad coverage, Jev-anrop får öka högst 1 %".
- **Behåll deterministisk** tills fler fall/repetitioner eller SSR visar
  samma mönster.
- **Kör fler repetitioner** innan beslut om +16 anrop bedöms som brus.

Oavsett val: ingen produktionsändring och PR #426 orörd. Beslutet gäller vilken
generering som används i nästa experiment (SSR/B4c), inte produktionsordningen.

## Answer

**Adoptionsbeslut 2026-10-23:** hybrid kandidatgenerering blir **ny
experimentstandard**. Detta är ett nytt, uttryckligt beslut och innebär **inte**
att B4b:s ursprungliga PASS/FAIL-kriterium omtolkas: B4b-artefakten behåller
`KEEP_DETERMINISTIC` eftersom `jev_calls_not_higher` fallerade.

| Villkor | Beslut |
| --- | --- |
| Hybrid kandidatgenerering | Ny experimentstandard |
| Jev-anrop | Högst +1 % tolereras i experimentfasen |
| False-sufficient | Får inte öka |
| Coverage | Får inte försämras |
| Jev:s semantiska beslut | Oförändrade |
| 40-parsbudget | Oförändrad |
| Produktionsadoption | Inte tillåten ännu |
| Tidigare förregistrerat resultat | Bevaras, omtolkas inte |

Latensökningen (161 s → 185 s, ~15 %) är större än anropsökningen och ska
undersökas i B4c med uppdelad tidsmätning: embeddingberäkning,
kandidatgenerering, prioritering och Jev-exekvering. Embeddings ska återanvändas
när de redan finns i Overgraph.

Nästa experiment: B4c fyrarmsfaktorial (deterministisk/hybrid ×
nuvarande/metadata). Produktionen är orörd.
