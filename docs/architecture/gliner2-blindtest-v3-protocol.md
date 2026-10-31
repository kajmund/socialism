# Blindtest v3 — protokoll för oberoende generaliseringstest (fryst före körning)

**Status:** material och protokoll frysta **innan** facit-annotering och **innan** någon
modellkörning på materialet. Syftet är inte att förbättra SWE — det är att pröva om den
uppmätta M1–M6-förbättringen håller på helt nya dokument. Manifest:
`crates/swe-gym/benchmarks/blindtest_v3_material.json`.

## Material (fryst)

Tre nya, publika svenska dokument som inte använts i blindtest v1/v2, D10 eller E1–E3 och
som inte ingår i testkorpusen:

| Id | Dokument | Källa |
|---|---|---|
| `goteborg-samarbetsavtal` | Mall för samarbetsavtal (Göteborgs Stad) | publik handling |
| `lansstyrelsen-upphandling-lieslatter` | Anbudsförfrågan/avtalsvillkor, upphandling lieslåtter (Länsstyrelsen Gotland) | publik handling |
| `nacka-avtalad-tjanst` | Avtalsbilaga, avtalad tjänst bostad med särskild service (Nacka kommun) | publik handling |

Fullständiga extraktioner och PDF:er förvaras **utanför repot**; i repot finns endast
id, publik käll-URL, beskrivning och SHA-256 (PDF + extraktion). Extraktionstexten är
läskällan för facit.

## Facit (annoteras efter denna frysning, före körning)

1. **Oberoende annotering:** läs den extraherade texten; kandidatgeneratorns eller
   GLiNER2:s utdata får aldrig konsulteras. Gold-spann är exakta delsträngar.
2. **Blandad svårighet:** både enkla behov (belopp, tidsperiod, datum, part) och svåra
   behov (operativ roll, kontextberoende part) ska ingå.
3. **Flervärdesbehov med OKÄND kardinalitet:** minst ett behov deklareras `MULTIPLE` med
   `UNKNOWN` kardinalitet. Antalet korrekta värden får **inte** exponeras för kedjan som
   `expected_count`; facit får bara användas för poängsättning. Detta förhindrar att M5
   gynnas av information som bara finns i facit.
4. **Svarsnivåfacit för D10:** för varje behov: förväntat svar, om det är besvarbart från
   dokumentet, och om ett korrekt svar är ett avstående (t.ex. extern rättskälla). Fryst
   före körningen.

## Jämförelse (en körning, inga justeringar)

- **Fryst ursprungskedja (M0)** mot **fryst M1–M6** (`gliner2-chain-m1m6-v1`, manifest
  med hashar och parametrar). Inga modell-, prompt- eller kontraktsändringar efter att
  resultatet börjat synas.
- Samma frysta material, samma kandidatpopulation och samma JEV-fixturlogik; nya JEV-svar
  frysas i en v3-fixture.
- Instrumentfel som upptäcks före den första riktiga körningen får rättas och dokumenteras;
  efter körningen fryses resultatet.

## Mått (redovisas separat)

| Mått | Varför |
|---|---|
| Lösta behov (M0 vs M1–M6) | faktisk marginalnytta på nya dokument |
| Falskt RESOLVED | säkerhet |
| **D10-svarskontamination** | påverkar slutsatsen, inte bara klausulen |
| Korrekta svar / korrekta avståenden | två separata mått, inte en procentsiffra |
| PARTIAL → RESOLVED (flervärde) | om M5 hjälper när kardinaliteten är okänd |
| Återhämtade falska negativa + kontrollgrupp | M6:s selektivitet |
| Exekveringskostnad (från tom cache) och experimentets merkostnad | ekonomi enligt fryst definition |

## Beslutskriterium

Först om den frysta M1–M6-kedjan håller på nya dokument — inklusive D10 på svarsnivå och
korrekta avståenden — finns underlag för att föra in M1–M6 i Investigation. 16/16 på det
gamla utvecklingsmaterialet eftersträvas inte.

## Reservation

Detta är ett generaliseringstest, inte en produktionsaktivering. Materialet är publika
handlingar; facit och resultat fryses med version och hashar. Fullständiga texter stannar
utanför repot enligt redigeringspolicyn.
