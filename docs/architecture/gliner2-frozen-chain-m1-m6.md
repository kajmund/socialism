# Fryst M1–M6-kedja (`gliner2-chain-m1m6-v1`)

**Status:** utvecklingsfasen är avslutad och M1–M6 är frysta som en sammanhållen
experimentversion. Kedjan är **inte** aktiverad i produktion och resultatet är **inte**
ett generaliseringsbevis. Manifest med hashar och parametrar:
`crates/swe-gym/benchmarks/gliner2_chain_frozen_v2.json`.

## Vad som är fryst

| Komponent | Fryst värde |
|---|---|
| GLiNER2 | `fastino/gliner2.5-multi-v1`, threshold 0.3, CPU |
| JEV | `jev-1.13.0` |
| Prompts | arm D `span-need-contrast-v1`; datum `span-date-v1`; återhämtning `span-need-recovery-v1` |
| Kontrakt | `backend/app/services/research/gliner/contract.py` (E1–E3), SHA-256 i manifestet |
| M1 | presentationsnormalisering (whitespace + datumartefakt); kanoniskt innehåll orört; original-hash + offset bevaras |
| M2 | spann-gräns-konsolidering vid strikt kanonisk innehållning i samma fall; inga proximity-sammanslagningar |
| M3 | roll-tie-break: deklarerad roll vinner endast när dess cue finns i spannets mening |
| M4 | behovsanpassat kontextfönster för PARTY: strukturellt block + rubrik, max 8 rader per riktning, inga godtyckliga teckengränser |
| M5 | kardinalitet på behovsnivå: SINGLE oförändrat; MULTIPLE med `expected_count` från facit; UNKNOWN löses aldrig enbart från värden; PARTIAL är explicit |
| M6 | selektiv återhämtning: exakt en kompletterande bedömning per triggad kandidat-NO; tre skydd (ingen blind omprövning, en komplettering, ingen automatisk RESOLVED) |
| Kostnad | `execution_jev_calls` (från tom cache) jämförs; `experiment_new_calls` är endast körningens replay-kostnad |

Kedjeordning, detektorer, gränser och hashar finns i manifestet. Alla frysta artefakter
(`blindtest_facit_v2*`, `jev_span_fixtures_v2*`, `blindtest_v2_arms_*`, revisionen) är
oförändrade sedan #450–#454.

## Mätt läge på utvecklingsmängden (fryst referens, inte bevis)

| Mått | Värde |
|---|---|
| Lösta behov | **15/16** (M0: 7/16) |
| PARTIAL | 1 (`v2-pm-07`, kandidatgenereringslucka) |
| Falskt RESOLVED | 0 |
| Exekvering JEV-anrop | **27** (M0: 32) |
| Modellinferenser i efterbearbetningsarmarna | 0 |
| Klausulnivå-kontamination (proxy) | 0 |

## Vad som inte är gjort

- **Ingen generalisering är visad.** De 16 fallen har utvecklat M1–M6. Därför är nästa
  experiment inte en förbättring av SWE utan ett test av om den uppmätta förbättringen
  håller på nya dokument.
- **D10 på svarsnivå är inte körd** på den förbättrade kedjan; endast en klausulnivåproxy
  finns. Riktig D10 (svarskontamination, korrekta svar, korrekta avståenden, falskt
  RESOLVED separat) ska köras i det nya blindtestet.
- **M5 UNKNOWN-kardinalitet** är implementerad och syntetiskt konformanstestad men har
  inget verkligt fall i v2.

## Nästa experiment: nytt oberoende blindtest

Fryst protokoll (ingen justering under körningen):

1. **Nytt material:** helt nya avtal, utanför korpusen och utanför v1/v2-materialet.
   Materialet ska innehålla både **enkla och svåra behov** samt **flervärdesbehov där
   antalet korrekta värden inte är känt i förväg** — annars gynnas M5 av ett
   `expected_count` som bara finns i facit.
2. **Oberoende facit:** annoteras genom att läsa dokumenten, utan kandidat-/GLiNER2-
   utdata; fryst före körningen. Svarsnivåfacit för D10 ingår.
3. **Jämförelse:** fryst ursprungskedja (M0) mot fryst M1–M6, utan ändringar.
4. **Mått:** lösta behov, falskt RESOLVED, **D10-svarskontamination**, korrekta svar och
   korrekta avståenden separat, PARTIAL→RESOLVED för flervärdesbehov, samt
   exekveringskostnad och faktiska merkostnader.
5. **Beslut:** först om kedjan håller på nya dokument finns underlag för att föra in
   M1–M6 i Investigation. 16/16 på det gamla materialet eftersträvas inte.
