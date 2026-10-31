# Blindtest v2 — ablationsarm M6: selektiv verifieringsåterhämtning

**Status:** eget experiment på det frysta blindtest v2-materialet. M1–M5 (PR #451–#453)
är oförändrade. M6 ändrar **hur verifiering kan återhämtas**, inte vad ett löst behov
betyder (det är M5) och inte kandidatgenereringen.

## Design

M6 är **inte** ett generellt andra JEV-försök. Ett första `NO` omprövas **exakt en gång**,
och bara när oberoende signaler talar emot det:

| Trigger (alla krävs) | Skydd |
|---|---|
| spannet är en **GLiNER2-kandidat** (förslag, aldrig gold) | inget `NO` leder automatiskt till nytt anrop |
| en **deterministisk detektor** identifierar spannet som ett värde av behovets typ | ingen omprövning utan oberoende stöd |
| **operativ roll** matchar behovets deklarerade roll (eller är obestämd) | roll- eller dokumentmismatch ger ingen omprövning |
| första bedömningen var `NO` | — |

Den enda kompletterande bedömningen använder en **ny promptversion**
(`span-need-recovery-v1`) som anger behovets operativa roll och ber modellen bedöma om
spannet självt uttrycker värdet i den rollen. Den återhämtade bedömningen går in i det
**vanliga kontraktet** (typ, roll, kardinalitet, evidens) — ingen automatisk RESOLVED.
Svaret nycklas av hela bedömningsuppgiften (case + spann-digest + kontext-digest).

**Kontrollgrupp:** kandidat-`NO` som inte passerar triggern omprövas aldrig; omprövade
korrekta `NO` räknas och måste förbli `NO`.

## Resultat

| Arm | Lösta | PARTIAL | Falskt RESOLVED | Kontamination | Exekvering JEV | Nya anrop |
|---|---|---|---|---|---|---|
| M0 | 7/16 | 0 | 0 | 0 | 32 | 0 |
| **M6 isolerat** | **9/16** | 0 | 0 | 0 | **35** (+3 kompletterande) | 3 |
| M12+M3+M4+M5 | 14/16 | 1 | 0 | 0 | 26 | 0 |
| **M12+M3+M4+M5+M6** | **15/16** | **1** | 0 | 0 | **27** (+1 kompletterande) | 0 (replay) |

### Återhämtning och kontroll (M6 isolerat)

| Mått | Värde |
|---|---|
| Kandidat-`NO` totalt | 7 |
| Triggers (oberoende stöd) | 3 |
| Återhämtade falska negativa (gold-matchande) | **2** |
| Omprövade men korrekt kvar som `NO` | **1** |
| Guard-blockerade korrekta `NO` (aldrig omprövade) | **4** |
| Kompletterande JEV-anrop | 3 (M6 isolerat); 1 (ackumulerat, resten replay) |

- **M6 isolerat:** `v2-pm-05` och `v2-sv-03` återhämtas (båda gold-matchande); `v2-if-06`
  omprövas men kvarstår korrekt `NO`; 4 korrekta `NO` (t.ex. datum som inte är
  tidsperioder, organisationsnummer, "bilaga 1") triggas aldrig.
- **Ackumulerat:** endast `v2-pm-05` återhämtas (+1 → **15/16**); `v2-sv-03` är redan löst
  av M1, och de övriga kandidat-`NO`:na skyddas av guard.
- **Inga falskt RESOLVED, ingen kontamination** i någon arm: återhämtade värden passerar
  samma typ-, roll- och kardinalitetskontrakt.

## Viktig begränsning: pm-07 kan inte återhämtas av M6

`v2-pm-07` förblir **PARTIAL** (1 av 2 parter). Den andra parten föreslogs **aldrig av
GLiNER2** — den finns bara som gold i utvärderingen. M6 kan bara återhämta spann som
faktiskt föreslogs; detta är en **kandidatgenereringslucka**, inte ett
verifieringsproblem. Det är därför M6 stannar på 15/16 i det ackumulerade läget, och
varför nästa steg inte är fler verifieringsförsök utan (a) en separat
kandidatgenereringsåtgärd om man vill jaga 16/16, eller (b) det nya oberoende blindtestet.

## Kostnad

- M6 isolerat: +3 kompletterande JEV-anrop (32 → 35 exekvering).
- Ackumulerat: +1 kompletterande anrop (26 → 27); inga nya modellinferenser. Övriga
  svar återanvänds ur frysta fixturer.
- M6 rör inte M1–M5:s artefakter eller den frysta baslinjen.

## Slutsatser

1. **Selektiv återhämtning fungerar och håller skydden:** 2 av 3 triggers var äkta falska
   negativa; 1 korrekt `NO` kvarstod `NO`; 4 korrekta `NO` omprövades aldrig.
2. **M6 ger +1 i ackumulerat läge (15/16)** — pm-05 var det enda verifieringsproblemet som
   kunde återhämtas. pm-07 kräver kandidatgenerering, inte verifiering.
3. **Även 15/16 (eller 16/16) bevisar inte generalisering:** de 16 fallen har använts för
   att utveckla M1–M6. Nästa steg är ett **nytt blindtest** där hela kedjan körs utan
   justeringar.

## Reservation

De 16 fallen är en diagnostisk utvecklingsmängd. Ingen bredare aktivering förrän ett nytt
osynligt dokumenttest passerat. M6 hålls separat från M5; frysta artefakter från
#450–#453 är oförändrade.
