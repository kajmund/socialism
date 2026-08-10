---
type: guide
title: Konfigurera en dag i tidslinjen
description: Så ställer du in injektioner, reaktionsronder och intervjuer för en simuleringsdag.
tags: [korningar]
---

# Konfigurera en dag i tidslinjen

Varje **dag** (tick) i en körning beskriver vad som händer den dagen i simuleringen: vilka budskap som injiceras, hur många reaktionsrundor som körs, och vilka intervjuer som planeras.

## Steg

1. Öppna körningen och gå till tidslinjen (i guiden, snabbläge eller fliken **Konfiguration**).
2. Klicka på en dag i tidslinjen för att öppna **Dagkonfiguration**.
3. På fliken **Injektioner**:
   - Välj **Tyst dag** om populationen ska reagera utan nytt budskap den dagen.
   - Lägg till **injektioner** (partipost, nyhetspost eller reklampost).
   - Välj avsändare och text — antingen från **Budskapsbiblioteket** eller fritt skriven text.
4. På fliken **Ronder & mätpunkter**:
   - Ange antal **reaktionsronder** (1–5).
   - Välj vilka **mätningar** som ska tas (t.ex. opinionsmätning, sentiment-baslinje, frasspridning).
5. På fliken **Intervjuer**:
   - Planera intervjuer med personas från populationen genom att skriva en prompt och lägga till intervjuplaner.
6. Spara och stäng modalen.

Du kan också **ändra ordning** på dagar, **lägga till** eller **ta bort** dagar, samt **förgrena** tidslinjen till version A och B (se [Skapa en ny körning](skapa-korning.md)).

## Obs

- En tyst dag har inga injektioner men populationen reagerar ändå i reaktionsronderna.
- Tidslinjen kan inte redigeras medan en simulering pågår.

## Relaterade guider

- [Skapa en ny körning](skapa-korning.md)
- [Reaktionsmodell i simuleringen](reaktionsmodell-i-simulering.md)
- [Hantera budskap](hantera-budskap.md)
