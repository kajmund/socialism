# GLiNER2/JEV blindtest v1 — D10-uppföljning på svarsnivå

**Status:** separat experiment efter PR #443. Analysen är helt offline över de
frysta artefakterna (`blindtest_facit_v1_eval.json` + `blindtest_d10_facit_v1.json`);
inga nya modellanrop, ingen ändring av blindtestets facit eller regler.

**Frågan:** producerar den frusna kombinationen *kontaminerade slutsatser* på de
20 blindtestfallen när evidensen följs hela vägen till ett svar — och var det
rapporterade falskt-RESOLVED-fallet ett semantiskt fel?

## Metod

Samma fyra-händelse-analys som D10 i `gliner2-jevspan-evaluation.md`: (1) hur behovet
löstes, (2) om operationskontraktet (grinden) skulle släppa igenom, (3) vilken slutsats
motorns evidens ger jämfört med svarsfacit, (4) klass — med kontrolljämförelsen att
enbart guldevidens ger rätt svar i samtliga fall. Svarsfacit annoterat genom läsning av
dokumenten (guldgransknings-v3-proceduren), fruset före analysen. Runner:
`crates/swe-gym/tools/d10_blindtest.py`; resultat: `benchmarks/blindtest_d10_v1.json`.

## Resultat (samtliga 20 fall)

| Utfall | Antal | Fall |
|---|---|---|
| Korrekt svar | 10 | bt-01, 04, 07, 08, 11, 12, 14, 15, 18, 20 |
| Korrekt svar, gräns-/morfologisk variant i evidensen (samma faktum) | 5 | bt-03, 05, 10, 13, 16 |
| Korrekt avstående (kontraktet höll på konkurrerande värden) | 1 | bt-17 |
| Korrekt avstående — nytt informationsbehov (extern rättskälla) | 1 | bt-09 |
| Felaktigt avstående (dokumentet svarar, motorn kunde inte) | 3 | bt-02, 06, 19 |
| **Kontaminerat svar** | **0** | — |
| **Korrekt svar trots felaktig evidens (dold risk)** | **0** | — |

## De två frågorna, besvarade

1. **bt-03 ("en dagfrist" vs "en dagfrist") är inte ett semantiskt fel.** Extraktorn
   hittade rätt faktum (30-dagars betalningsfrist) med en för lång spannvänsterkant
   ("inom"). Slutsatsen den evidensen ger är korrekt; det är en spannavgränsnings-
   skillnad — samma klass som D8:s gräns-artefakter. Den hör hemma i nästa
   kontraktsversion (trim/extend-varianter, jfr JevSpan-idé 5 i inventeringen), inte
   i verifieraren.
2. **bt-09 ("en laghänvisning") är inte en missad tidsperiod.** Dokumentet anger
   uppsägningstiden genom laghänvisning; ett numeriskt värde kräver en extern
   rättskälla. Motorns avstående är korrekt, och fallet klassas som ett nytt
   informationsbehov (jfr operationernas `NeedMore`-loop) — en annan uppgift än NER.

## Slutsats

På de 20 nya, verkliga avtalsfallen finns **ingen svarskontamination och ingen dold
felaktig evidens** i den frusna kombinationen: 15 av 20 slutsatser korrekta (10 rena,
5 med samma-faktum-variant i evidensen), 2 korrekta avståenden, och de 3 felaktiga
avståendena är rena recall-missar (datum utan sifferformat ×2, rekryteringsersättning)
— inte felaktiga svar. Den enda "felaktigt godkända" evidensen i hela setet är
gräns-/morfologiska varianter av rätt faktum.

**Därmed:** blindtestets 14/20 är inte en överskattning som döljer kontaminerade
slutsatser — men de 3 felaktiga avståendena bekräftar per-typ-ojämnheten från PR #443
och pekar på nästa kontraktsexperiment (ordformsdatum, datumintervall, spann-
avgränsningsekvivalens), som är planerat separat. Inget produktionsbeslut här.
