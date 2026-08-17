---
type: guide
title: Intervjua persona i simulering
description: Så chattar du med en simulerad persona om vad den sett i flödet — efter vald simuleringsdag.
tags: [korningar, personas]
---

# Intervjua persona i simulering

Efter en avslutad simulering kan du **intervjua** en persona direkt i resultatet. Personan svarar utifrån vad den *sett* i flödet fram till den dag du väljer — inte senare händelser.

## Steg

1. Öppna körningen via **Öppna resultat**.
2. Expandera ett sparat **försök** (och rätt variant vid A/B).
3. I **flödet**, vid en agents kommentar eller inlägg: välj **Intervjua** (pratbubbla) eller klicka på agentens namn och intervjua därifrån.
4. I intervjurutan:
   - Välj **persona** om flera finns i populationen.
   - Välj **efter tick** — vilken simuleringsdag kontexten ska gälla till och med. Personan ser inte inlägg från senare dagar.
5. Skriv frågor och skicka. Personan svarar i intervjuläge utifrån flödeskontexten.
6. Välj **Rensa** om du vill börja om chatten för samma persona och tick.

Intervjun sparas per körning, försök, variant, persona och tick — du kan återkomma senare.

## Obs

- Intervju kräver en population med personas och tick-markörer i resultatet.
- Detta är en **manuell uppföljning** efter simuleringen, skild från **planerade intervjuer** i tidslinjen (se [Konfigurera en dag i tidslinjen](konfigurera-dag-i-tidslinjen.md)).
- Persona måste ha varit aktiv i simuleringen för att ge meningsfulla svar.

## Relaterade guider

- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
- [Skapa och redigera persona](skapa-och-redigera-persona.md)
- [Konfigurera en dag i tidslinjen](konfigurera-dag-i-tidslinjen.md)
