# GLiNER2/JEV — Generaliseringsprotokoll (blindtest)

**Status:** Experimentet avslutat och mergat i `main`. Detta protokoll gäller för nästa
milstolpe: ett blindtest på helt nya, verkliga avtal. Ingen åtgärd här är påbörjad.

## Fryst implementation (får inte ändras under testet)

| Komponent | Fryst värde |
|---|---|
| GLiNER2 | `fastino/gliner2.5-multi-v1`, threshold 0.3, CPU-inferens, isolerad venv |
| JEV-prompt | **arm D**: `span-need-contrast-v1` — behovsspecifik + kontrastiv, ett enda beslut per kandidat |
| Evidenskontrakt | Typkontroll (ordform-datum inkluderat), kanonisk spann-normalisering (alla brackets bort), VERIFIED / AMBIGUOUS / REJECTED med AMBIGUOUS härlett från konkurrerande kandidater till samma operativa roll |
| Kandidatgenerator | Befintlig deterministisk extraktor + GLiNER2 som behovsstyrd, valbar spann-förslagsgivare (vid kvarstående REQUIRED-gap) |
| Roller | GLiNER2 föreslår aldrig entitetstyper som godkänns automatiskt; JEV avgör betydelsen; SWE:s kontrakt avgör användning |

## Principer

1. **Oberoende facit:** nya dokument annoteras utan att kandidatgeneratorernas (regex- eller
   GLiNER2-) resultat används som facit; annoteringarna fryses med version och proveniens
   (samma procedur som guldgranskningen v3).
2. **Samma jämförelse:** befintlig extraktor ensam mot extraktor + GLiNER2 + JEV (arm D),
   med K-expansion som ekonomisk referens.
3. **Samma mått:** unik kandidattäckning, korrekt lösta behov, falskt RESOLVED per unikt
   `need_id`, svarskorrekthet (answer contamination inkl. kontrolljämförelse), kostnad per
   ytterligare löst behov (alla inferenser och JEV-anrop räknade, frysta i fixturen).
4. **Per frågetyp:** resultaten redovisas uppdelade efter juridisk frågetyp (uppsägnings-
   villkor, ansvarsfördelning, ersättning, tidsfrister, parter m.fl.) — för att upptäcka
   om kombinationen fungerar ojämnt.
5. **Ingen justering under testet:** första körningen är den ärliga generaliseringsmätningen.
   Eventuella förbättringar får bli ett nytt, separat experiment med ny prompt-/kontraktsversion.

## Beslutströskel

- Håller den frusna kombinationen på nya dokument → underlag för nästa beslut: börja
  integrera GLiNER2 som **valbar förmåga i Investigation**.
- Håller den inte → marginalnyttan är begränsad till testmaterialet; ingen integration.

## Nuvarande status (uppdaterad 2026-10-29 — blindtest v1 utfört)

**Blindtest v1 — första ärliga generaliseringsmätningen, körningen gjordes en gång
enligt protokollet.** Material: tre verkliga avtal utanför korpusen (Sponsoravtal klubben
2017, ett anställningsavtal (2020), Konsulttjänst Avtal
konsultbolaget 2020-06-01), 20 klausulfall med oberoende facit
(guldgransknings-v3-proceduren, fruset före körningen). Runner:
`crates/swe-gym/tools/run_blindtest.py`; artefakter: `blindtest_facit_v1.json`,
`blindtest_facit_v1_eval.json`, `blindtest_facit_v1_candidates.json`.

| Mått | Resultat |
|---|---|
| Lösta behov, baslinje (extraktor + JEV) | **0/20** — korpus-regexerna träffar nästan ingenting på nya dokument |
| Lösta behov, frusen kombination (S2) | **14/20** — 19 GLiNER2-inferenser + 45 JEV-anrop |
| Unik kandidattäckning (generator missar, GLiNER2 hittar) | 13 spann, **9/13 JEV-överlevnad** |
| Falskt RESOLVED per need_id | 1 (bt-03 — gräns-artefakt: extraktorn hittade rätt värde med fel gräns, "en dagfrist" vs "en dagfrist") |
| AMBIGUOUS (korrekt återhållet) | 1 (bt-17 — två konkurrerande värden i samma roll) |
| Reproducerbarhet | omkörning återskapade alla aggregat med 0 nya JEV-anrop |

**Per frågetyp:** ersättning 4/5, parter 3/3, ansvarsbegränsning 1/1, tidsfrister 5/9
(datum utan sifferformat — "ett ordformsdatum", "ett datumintervall", "ett datumintervall" — löses inte),
uppsägningsvillkor 1/2 ("ett veckotal" ✓; "en laghänvisning" — laghänvisning i stället för
tidsperiod — löses inte).

**Beslutsunderlag:** kombinationen håller på nya dokument — 0→14 lösta behov — men
ojämnt per frågetyp, på tre dokument. Detta är underlag för beslutet att börja integrera
GLiNER2 som valbar förmåga i Investigation, **inte** beslutet i sig. Öppna punkter inför
det beslutet: (1) större dokumentset för säkrare per-typ-siffror, (2) svarsnivå-
kontaminationen (D10-proceduren) är ännu inte följd på blindtestet, (3) gräns-artefakt-
klassen ("en dagfrist") och datum-formaten är kandidater till nästa kontraktsversion —
ett separat experiment enligt protokollets princip 5. **Ingen produktionsintegration.
GLiNER2 förblir experimentell och valbar.**

## Slutsatser som ska dokumenteras (frysta med resultatet, inga regeländringar)

1. **Baslinjens 0/20 är ett eget fynd.** Den deterministiska kandidatgeneratorns täckning
   är starkt anpassad till mallkorpusens formuleringar (brackets-belopp, hårdkodade
   partsnamn, korpus-nyckelord). På verkliga avtal kollapsar den nästan helt. Detta är
   lika viktigt som hybridens 14/20: det förklarar *varför* GLiNER2 behövs och var
   generaliseringsgränsen faktiskt går.
2. **"en laghänvisning" (bt-09) ska inte tolkas som en missad tidsperiod.** Det är ett nytt
   informationsbehov som kräver en extern rättskälla — en annan uppgift än NER, och
   inget GLiNER2 förväntas extrahera som ett numeriskt värde. Facit och siffror är
   frusna som de uppstod; tolkningen bokförs här och hör hemma i D10-uppföljningen
   (klass "korrekt avstående / nytt behov"), inte som en regeländring i blindtestet.
3. **Om bt-03 ("en dagfrist") är ett semantiskt fel eller enbart en
   spannavgränsningsskillnad avgörs i D10-uppföljningen** på samtliga 20 fall — inte
   här, och inte i facit.

## Blindtest v2 — andra ärliga mätningen (utförd 2026-10-30)

**Material:** tre nya, verkliga avtal utanför korpusen som varken v1, D10 eller E1–E3
använt: (1) ett leverantörsvillkor för konsulttjänster, (2) ett servitutsavtal,
(3) en försäkringsspecifikation med villkor. Dokumenten är privata och ingår **inte**
i repot. 16 klausulfall med ett behov vardera; oberoende facit annoterat genom att LÄSA
den extraherade texten. **Repot är publikt:** facit, eval och JEV-fixture är redigerade —
klausultexter och spannvärden representeras av SHA-256-digest, aldrig av text; de
fullständiga artefakterna förvaras lokalt utanför repot. Runner: `crates/swe-gym/tools/run_blindtest_v2.py` — den **färdiga** kedjan
(E1–E3-kontraktet importerat från `backend/app/services/research/gliner/contract.py`,
arm D + `span-date-v1`, GLiNER2 `fastino/gliner2.5-multi-v1` threshold 0.3). JEV-svar
frysta i `jev_span_fixtures_v2.json`; omkörning återskapade alla aggregat med 0 nya
JEV-anrop. Mätningen gjordes en gång enligt protokollet; endast en mappningsbugg i
instrumentets false-RESOLVED-mått rättades före frysning (kedja och facit oförändrade).

| Mått | Resultat |
|---|---|
| Lösta behov, baslinje (extraktor + JEV) | **2/16** |
| Lösta behov, frusen kombination (S2) | **7/16** |
| Unik kandidattäckning (verifierad) | 1/2 |
| Falskt RESOLVED per need_id | **0** |
| AMBIGUOUS (korrekt återhållet) | 2 (v2-pm-03, v2-sv-01) |
| Kostnad per ytterligare löst behov (S2) | 13 inferenser + 24 JEV-anrop för 5 extra behov |

**Per frågetyp:** avtalstid 2/2, ersättning 2/3, tidsfrister 3/5, parter 0/4,
ansvarsbegränsning 0/1, uppsägningsvillkor 0/1.

### Slutsatser (frysta med resultatet, inga regeländringar)

1. **Kedjan håller riktningsmässigt på nya dokument:** 2→7 lösta behov (+5), 0 falskt
   RESOLVED och 2 korrekt AMBIGUOUS. Absolutnivån är lägre än v1 (14/20), men materialet
   är andra dokumenttyper (leverantörsvillkor, servitut, försäkringsspecifikation) —
   inte fler av samma avtalstyp. Det adresserar v1:s öppna punkt om större/annat
   dokumentset, men ger inte v1:s per-typ-säkerhet.
2. **Per-typ-siffrorna är ojämna — två bokförda orsaker.** (a) E3-rollklassningen kan
   exkludera ett korrekt ansvarstak när en MONEY-kue ("belopp") ligger närmare spannet
   än LIABILITY-kueen (v2-pm-02: JEV YES, roll MONEY → exkluderas). (b) Det integrerade
   kontraktet antar ett värde per behov, så flerpartinehov blir AMBIGUOUS (v2-sv-01),
   medan v1-instrumentet tillät flera gold-värden i samma behov. Detta är en känd
   begränsning i den valda kontraktsformen, inte en regeländring i efterhand.
3. **Artefaktklasser för en separat nästa version** (protokollets princip 5):
   radbrytningsartefakter inuti spann (v2-pm-05, v2-sv-03) gav JEV NO trots korrekt
   innebörd; minimala klausuler (v2-if-05, v2-if-06) gav UNCERTAIN för korrekta
   partsnamn; en gold-span avvisades felaktigt av JEV (v2-pm-07: kundens partnamn fick NO).
   Nästa experiment: whitespace-normalisering före spannbildning och klausulfönster med
   mer kontext — som ny version, inte som justering här.
4. **Beslutsunderlag:** blindtest v2 ger underlag för fortsatt integration som **valbar,
   avstängd** förmåga, men **inte** för bredare aktivering: parter/ansvarsbegränsning
   och artefaktklasserna är för svaga. Svarsnivåkontamination (D10) är inte mätt på
   v2-materialet och är nästa steg före bredare aktivering.

**Artefakter (redigerade för publikt repo):** `blindtest_facit_v2.json`,
`blindtest_facit_v2_eval.json`, `jev_span_fixtures_v2.json`,
`crates/swe-gym/tools/run_blindtest_v2.py`. Varje fall bär `clause_sha256` och
`span_canon_sha256`; extraktionshasharna i `material` verifierar läskällan. Körbara
fullartefakter (klausuler, spann, kandidater) hålls utanför repot och committas aldrig.

**Redigeringspolicy (gäller alla blindtester):** avtalsdokument, klausultexter,
spannvärden och identifierande namn committas aldrig; committade artefakter får bara
innehålla typ/id, aggregerade mått, domar och SHA-256-digest. Fullständiga artefakter
förvaras lokalt utanför repot för omkörning och verifiering.
