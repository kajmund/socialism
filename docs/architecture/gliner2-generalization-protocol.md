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
enligt protokollet.** Material: tre verkliga avtal utanför korpusen (Sponsoravtal NKK
2017, Anställningsavtal Erik Fremred AB signerat 2020-05-04, Konsulttjänst Avtal
Ateles/Erik Fremred AB 2020-06-01), 20 klausulfall med oberoende facit
(guldgransknings-v3-proceduren, fruset före körningen). Runner:
`crates/swe-gym/tools/run_blindtest.py`; artefakter: `blindtest_facit_v1.json`,
`blindtest_facit_v1_eval.json`, `blindtest_facit_v1_candidates.json`.

| Mått | Resultat |
|---|---|
| Lösta behov, baslinje (extraktor + JEV) | **0/20** — korpus-regexerna träffar nästan ingenting på nya dokument |
| Lösta behov, frusen kombination (S2) | **14/20** — 19 GLiNER2-inferenser + 45 JEV-anrop |
| Unik kandidattäckning (generator missar, GLiNER2 hittar) | 13 spann, **9/13 JEV-överlevnad** |
| Falskt RESOLVED per need_id | 1 (bt-03 — gräns-artefakt: extraktorn hittade rätt värde med fel gräns, "inom 30 dagar" vs "30 dagar") |
| AMBIGUOUS (korrekt återhållet) | 1 (bt-17 — två konkurrerande värden i samma roll) |
| Reproducerbarhet | omkörning återskapade alla aggregat med 0 nya JEV-anrop |

**Per frågetyp:** ersättning 4/5, parter 3/3, ansvarsbegränsning 1/1, tidsfrister 5/9
(datum utan sifferformat — "12 maj", "10-11 juni", "30 juni-2 juli" — löses inte),
uppsägningsvillkor 1/2 ("2 veckor" ✓; "Enligt LAS" — laghänvisning i stället för
tidsperiod — löses inte).

**Beslutsunderlag:** kombinationen håller på nya dokument — 0→14 lösta behov — men
ojämnt per frågetyp, på tre dokument. Detta är underlag för beslutet att börja integrera
GLiNER2 som valbar förmåga i Investigation, **inte** beslutet i sig. Öppna punkter inför
det beslutet: (1) större dokumentset för säkrare per-typ-siffror, (2) svarsnivå-
kontaminationen (D10-proceduren) är ännu inte följd på blindtestet, (3) gräns-artefakt-
klassen ("inom 30 dagar") och datum-formaten är kandidater till nästa kontraktsversion —
ett separat experiment enligt protokollets princip 5. **Ingen produktionsintegration.
GLiNER2 förblir experimentell och valbar.**

## Slutsatser som ska dokumenteras (frysta med resultatet, inga regeländringar)

1. **Baslinjens 0/20 är ett eget fynd.** Den deterministiska kandidatgeneratorns täckning
   är starkt anpassad till mallkorpusens formuleringar (brackets-belopp, hårdkodade
   partsnamn, korpus-nyckelord). På verkliga avtal kollapsar den nästan helt. Detta är
   lika viktigt som hybridens 14/20: det förklarar *varför* GLiNER2 behövs och var
   generaliseringsgränsen faktiskt går.
2. **"Enligt LAS" (bt-09) ska inte tolkas som en missad tidsperiod.** Det är ett nytt
   informationsbehov som kräver en extern rättskälla — en annan uppgift än NER, och
   inget GLiNER2 förväntas extrahera som ett numeriskt värde. Facit och siffror är
   frusna som de uppstod; tolkningen bokförs här och hör hemma i D10-uppföljningen
   (klass "korrekt avstående / nytt behov"), inte som en regeländring i blindtestet.
3. **Om bt-03 ("inom 30 dagar") är ett semantiskt fel eller enbart en
   spannavgränsningsskillnad avgörs i D10-uppföljningen** på samtliga 20 fall — inte
   här, och inte i facit.
