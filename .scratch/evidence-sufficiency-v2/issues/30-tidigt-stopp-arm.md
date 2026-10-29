# Tidigt stopp – experimentarm

Type: task
Status: resolved
Blocked by: 29

## Question

Vad händer när SWE faktiskt får avsluta efter första verifierade, relevanta och
blockerande motsägelsen — jämfört med full konfliktkartläggning?

- Jämför D-konfigurationen med `conflict_confirmed`-stopp mot dagens
  full-mapping-beteende, två live-repetitioner.
- Mät: sparade Jev-anrop, förändrad latens, false-sufficient (får inte öka),
  antal stopp som bygger på konflikt som senare visar sig felaktig eller
  irrelevant, samt hur ofullständig coverage märks.
- Ett tidigt stopp får endast ske på en verifierad, relevant, blockerande
  konflikt. Full konfliktkartläggning kräver fortsatt täckning eller uttrycklig
  `incomplete`-markering vid budgetslut.
- Behåll nuvarande produktionsbeteende tills båda målen är mätta; ändra inte
  beslutslogiken utan eget test.

Leverans: armartefakt, PASS/FAIL för tidigt stopp och rekommendation.

## Låst protokoll före körning (2026-10-23)

- **Existential mode:** avsluta när en verifierad, relevant och blockerande
  konflikt har hittats; resultat `CONFLICT_FOUND`, undersökningsstatus `PARTIAL`,
  evidensstatus oförändrad. Aldrig `SUFFICIENT` på grund av stoppet.
- **Exhaustive mode:** fortsätt alla valda kandidatpar inom 40-parsbudgeten.
- Båda använder D-konfigurationen (hybrid + metadata), samma Jev-bedömning och
  två live-repetitioner.
- Mät: faktiskt undvikna Jev-anrop, redan påbörjade anrop, avbrutna anrop (vi
  avbryter inte pågående), faktisk väggtid, false-sufficient, stopp på
  felaktig/irrelevant konflikt, och att `PARTIAL` aldrig presenteras som
  fullständig kartläggning.
- Produktionsbeteendet är oförändrat; ingen generisk `STOP_WHEN_VERIFIED`-ram
  byggs i detta steg.

## Answer

**Körd 2026-10-23** (commit `a6b609cb`), två live-rep per läge, D-konfiguration.
Produktionsbeteendet är oförändrat.

| Mått | Exhaustive | Existential |
| --- | ---: | ---: |
| Körningar / rätt | 16 / 16 | 16 / 16 |
| False-sufficient | 0 | 0 |
| Jev-anrop | 1 516 | 1 397 |
| Väggtid | 125,3 s | 116,9 s |
| Utvärderade par | 180 | 61 |
| Skippade par-anrop | 0 | 119 |
| In-flight vid stopp | 0 | 34 |
| PARTIAL-körningar | 0 | 4 |
| Ogiltiga/irrelevanta stopp | 0 | 0 |
| Sufficient presenterat som PARTIAL | 0 | 0 |

**Faktiskt undvikna Jev-anrop:** 119 (7,8 %). **Faktisk väggtidsvinst:** 8,4 s
(6,7 %). Ytterligare 34 anrop var redan påbörjade när konflikten hittades och
slutfördes; de räknas inte som sparade. Inga stopp byggde på en konflikt som
senare löstes eller var irrelevant, och ingen `PARTIAL`-undersökning
presenterades som fullständig kartläggning.

Stoppet ändrar aldrig det underliggande sufficiency-beslutet: `CONFLICT_FOUND`
+ `PARTIAL` + oförändrad evidensstatus, aldrig `SUFFICIENT` på grund av stoppet.
Ingen generisk `STOP_WHEN_VERIFIED`-ram byggdes; den konkreta konfliktregeln
ligger kvar som experiment.

Nästa: ticket 31 (golden-facit QA och versionerat facit) innan siffrorna används
för produktionsadoption.
