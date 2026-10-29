# Datumförståelse och spannekvivalens — två isolerade experiment på blindtest v1

**Status:** separat experimentomgång efter PR #443/#444. Blindtest v1:s artefakter
är **inte ändrade eller överskrivna** — varje experiment har egna versioner och
egna resultatfiler. Fryst baslinje: GLiNER2 + JEV arm D som i PR #443.

## Problemuppdelningen

Diagnosen ur de frusna artefakterna visade två olika felklasser — därför mäts de separat:

| Experiment | Felklass | Mekanism (uppmätt) |
|---|---|---|
| **E1 Datumförståelse** | bt-02 ("ett ordformsdatum"), bt-06 ("ett datumintervall", "ett datumintervall") | GLiNER2 föreslog exakt rätt spann, men **JEV arm D sade NO** till datum utan årtal och datumintervall — felet sitter i verifieringsfrågan, inte i kandidatgenereringen |
| **E2 Spannekvivalens** | bt-03 ("en dagfrist" vs "en dagfrist") m.fl. | Samma faktum med olika textgränser — en fråga om kanonisk representation och korrekt utvärdering |

bt-19 (rekryteringsersättning) ingår i ingetdera: GLiNER2 föreslog ingenting och JEV
sade NO till guldet som "Belopp" — ett generations- och konceptgap
(ersättningsuttryck, SEVERANCE_VALUE-klassen), inte ett datum- eller gränsproblem.

## E1 — Datumförståelse (egen version: `span-date-v1`)

Ändring (endast för DATE-behov, arm D orörd för allt annat): en datum-specifik
verifieringsfråga som accepterar **partiella datum och datumintervall utan årtal** —
representationen fyller aldrig i ett årtal som inte står i texten ("SWE får inte hitta
på ett årtal bara för att fylla ett kontrakt"). GLiNER2-kandidaterna återanvänds
frysta. Script: `tools/exp_dates.py`; resultat: `benchmarks/blindtest_date_v1.json`;
5 nya JEV-svar frysta under `span-date-v1`.

| Fall | Frusen arm D | `span-date-v1` |
|---|---|---|
| bt-02 "ett ordformsdatum" | ej löst | **löst** |
| bt-06 "ett datumintervall", "ett datumintervall" | ej löst | **löst** |
| bt-07 "ett ISO-datum" (regressionskontroll) | löst | **löst** |
| bt-18 "2021-01-01" (regressionskontroll) | löst | **löst** |

Datumfall: 2/4 → **4/4**, inga regressioner.

## E2 — Spannekvivalens (deterministisk, inga modellanrop)

Kanonisk-värde-normalisering, tillämpad post hoc på de frusna spannen (jämförelse och
dedup av konkurrerande värden): brackets/whitespace (frusen regel) + strippning av
ledande grammatiska ord från en **sluten lista** {inom, i, under, senast, den, det,
de, en, ett} — kvantifierare som minst/högst/cirka strippas **inte**, de bär
semantisk laddning — + genitiv-normalisering av enheter (dagars→dagar,
veckors→veckor, månaders→månader, års→år, timmars→timmar). Script:
`tools/exp_span_equiv.py`; resultat: `benchmarks/blindtest_span_v1.json`.

Flippar: **bt-03 false_resolved → resolved** ("en dagfrist" = "en dagfrist"),
bt-17 ambiguous → resolved (se avvägningen nedan).

## D10-replay (båda experimenten, mot den frusna D10-tabellen)

Script: `tools/replay_d10_v2.py`; resultat: `benchmarks/blindtest_d10_v2.json`.

| Utfall | Frusen D10 | Efter E1+E2 |
|---|---|---|
| Korrekt svar | 10 | **14** |
| Korrekt svar, gräns-/morfologisk variant | 5 | 3 |
| Korrekt avstående (kontraktet höll) | 1 | 0 |
| Korrekt avstående — extern rättskälla | 1 | 1 (bt-09) |
| **Felaktigt avstående** | **3** | **1 (bt-19)** |
| Kontaminerat svar | 0 | **0** |
| Korrekt svar trots felaktig evidens | 0 | 1 (bt-17) |

**Målet nått:** minst 2 av 3 felaktiga avståenden borta (bt-02, bt-06), 0
kontaminerade svar, inga tidigare korrekta svar försämrade. Plus: bt-03:s
false-RESOLVED är nu ett rent korrekt svar.

**Avvägningen, öppet redovisad:** spannekvivalensen gör att bt-17 ("ett månadstal med
ett veckotal uppsägningstid") inte längre hålls tillbaka av kontraktets
AMBIGUOUS-tröskel — den tidigare korrekta avståendet blir ett svar med ett
konkurrerande värde ("ett veckotal") kvar i evidensen. Det är den enda dold-risken i
replayen, och den hanteras inte här: operationens entydighetskrav (kontext-JEV,
§29-mekanismen) är den befintliga vägen om nästa version vill behålla avståendet.

## Beslutsunderlag

Kombinationen efter E1+E2: **18/20 korrekta svar eller korrekta avståenden på nya,
verkliga avtal**, 0 kontamination, 1 dold risk (bt-17) och 1 kvarstående felaktigt
avstående (bt-19, generations-/konceptgap). Fortfarande: inga fler modeller, inga
fler JEV-steg i grundflödet (span-date-v1 ersätter arm D endast för DATE-behov),
ingen förändring av SWE:s grundarkitektur. Detta är — tillsammans med PR #443/#444 —
det samlade underlaget för integrationsbeslutet. Beslutet fattas inte här.
