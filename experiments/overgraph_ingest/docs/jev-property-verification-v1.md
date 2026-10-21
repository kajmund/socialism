# Spec: Jev-verifiering av dokumentegenskaper

**Projekt:** Socialism, `kajmund/socialism`
**Arbetsområde:** `experiments/overgraph_ingest/`
**Omfattning:** Ett litet, isolerat experiment. Ingen ändring av deterministisk discovery, taxonomi, gold eller produktionspipeline.

## 1. Syfte och hypotes

Den deterministiska discoverysignalen har hög recall men en precision som är svår att läsa, eftersom en stor del av de registrerade falska positiva preliminärt är facitluckor snarare än extraheringsfel.

**Hypotes:** Jev kan fungera som en icke-hård verifierare av föreslagna dokumentegenskaper — reducera genuina felträffar (`wrong_property`, `wrong_relation_or_polarity`) utan att avvisa korrekta träffar — och därmed höja precisionen utan att tappa recall.

Jev används här **inte** som ett hårt filter och inte som facitskapare.

## 2. Kontrollgrupper

| Grupp | Urval | Roll | Grundsanning |
|---|---|---|---|
| **Positive controls** | ~20 dokument-egenskaps-par från gold-positiva | Mäta felaktig avvisning (recallförlust) | Verifierad (passage-gold) |
| **Genuine-error controls** | ~10 preliminära fel (5 `wrong_property` + 5 `wrong_relation_or_polarity`) | Mäta förmåga att fälla fel | Preliminär AI-granskning |
| **Gold-gap candidates** | ~20 preliminära `gold_gap` | Triage/överensstämmelse, **inte facit** | Öppen fråga |

Totalt ~50 Jev-anrop. Urvalet är deterministiskt (jämnt spridda index), redovisat och hashat.

**Metodregel:** Gold-gap-gruppen är inte ett mål som Jev ska träffa. Om Jev och den preliminära granskningen **överensstämmer** på att egenskapen är korrekt, är det konvergent bevis för att facit ska kompletteras — men det blir en flagga för oberoende mänsklig granskning, inte en verifierad etikett. Om de är oense, går fallet till manuell granskning.

## 3. Jev-kontrakt

- En bedömning per dokument-egenskaps-par. Ingen batchning.
- Jev ser endast: egenskapsdefinitionen från den frysta taxonomin, den föreslagna egenskapen (`class_id`, `polarity`, `value`), och det relevanta klausulmaterialet (citerad TextUnit + klausulrubrik + föregående/nästa TextUnit).
- Jev ser **inte**: testfrågan, gold, granskningsklassificeringen eller facit.
- Jev returnerar `SUPPORTED` / `UNSUPPORTED` / `UNDECIDED` och pekar på en av de presenterade TextUnits. Källan valideras med `validate_source` (exakt delsträng); en ohängd källhänvisning räknas som `UNSUPPORTED`.
- `UNDECIDED` är ett förstklassigt utfall och får aldrig tystas ned.

Återanvänd `doctags/extract.py` (excerpt-förankrad extraktion) och `doctags/source.py`.

## 4. Mått

Förväxlingsmatris mot kontrollgrupperna:

| Grupp | Jev SUPPORTED | Jev UNSUPPORTED | Jev UNDECIDED |
|---|---|---|---|
| Positive | rätt behåll | **felaktig avvisning** | osäkert, inte avvisat |
| Genuine error | missat fel | rätt fällt | osäkert, inte fällt |
| Gold-gap candidate | överensstämmelse | oenighet → granskning | osäkert → granskning |

Rapporterade tal:

| Mått | Definition |
|---|---|
| `keep_rate` (positive controls) | Andel gold-positiva som Jev `SUPPORTED`; mål nära 100 % |
| `reject_rate` (error controls) | Andel genuina fel som Jev `UNSUPPORTED`/`UNDECIDED` |
| `error_miss_rate` | Andel genuina fel som Jev `SUPPORTED` |
| `gold_gap_agreement` | Andel gold-gap-kandidater som Jev `SUPPORTED` |
| `undecided_rate` | Andel `UNDECIDED` per grupp |
| `hard_filter_simulation` | Simulerad recall/precision om `UNSUPPORTED` skulle filtreras bort — redovisas, appliceras inte |

## 5. Anti-läckage

1. Jev-prompten innehåller aldrig granskningsklassificering, gold eller frågetext.
2. Jev skapar inte det facit det utvärderas mot; gold-gap-gruppen är triage, inte facit.
3. Taxonomi och discovery är oförändrade under experimentet.
4. Körningen fryses med manifest (taxonomihash, urvalshash, promptversion, Jev-modell).

## 6. Återanvändning

- `overgraph_ingest/retrieval/document_properties.py` — deterministisk extraktion och egenskapsmodell.
- `overgraph_ingest/doctags/extract.py` + `source.py` — Jev-extraktion och källvalidering.
- `overgraph_ingest/retrieval/gold_map.py` — excerptlokalisering.
- `retrieval_gold/document_properties/review-false-positives-sample-v1.json` — kontrollurvalet.

## 7. Beslutskriterier

| Utfall | Slutsats |
|---|---|
| `keep_rate` ≈ 100 % och `reject_rate` hög | Jev tillför verklig precision utan recallförlust; speca en mjuk integration |
| `keep_rate` låg (Jev avvisar gold-positiva) | Jev är inte säker som verifierare; integrera inte |
| `gold_gap_agreement` hög | Bekräftar att facit bör kompletteras (oberoende) före integration |
| `undecided_rate` hög | Verifieringen är osäker; räkna med djupare analys i pipelinen |

**Klart när vi kan säga:** om Jev kan reducera genuina felträffar utan att avvisa korrekta träffar, och om gold-gap-misstanken bekräftas. Ingen ändring av discovery, taxonomi eller produktion sker innan dess.
