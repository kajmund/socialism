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

## Nuvarande status (oförändrad tills vidare)

Experimentellt bevisad marginalnytta på testmaterialet (6 unika spann, 6/6 JEV-överlevnad,
+4 lösta behov på utmaningssetet). **Ingen verifierad generalisering. Ingen
produktionsintegration.** GLiNER2 förblir experimentell och valbar.
