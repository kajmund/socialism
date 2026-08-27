---
type: guide
title: Läsa simuleringsresultat
description: Så utforskar du försök, flöde och jämförelser efter en avslutad simulering.
tags: [korningar, rapporter]
---

# Läsa simuleringsresultat

När en simulering är klar visas resultatet som **försök** på körningen. Du kan ha flera försök på samma körning utan att radera tidigare.

## Steg

1. Öppna **Körningar** och välj **Öppna resultat** på kortet eller raden.
2. Medan simuleringen **körs** visas **Live-flöde** överst på Resultat: till vänster det resulterande **Flödet** som växer i realtid, till höger **Aktivitet**. Växla mellan **Flöde**, **Aktivitet** eller **Båda**. Injektorinlägg ligger i en fällbar sektion högst upp i flödet. Aktiviteten är grupperad per dag (senaste dagen först). Inom varje dag ligger händelserna efter klockslaget, senaste överst. Klockan följer händelseordningen — ett inlägg kan inte gillas innan det har skapats. Gillade inlägg och kommentarer är ihopfällda — klicka på ordet **inlägg** eller **kommentar** för att läsa texten och se gilla, ogilla och dela. Öppnad gilla-rad visar också *Gillat av* plus namnet. Nya kommentarer säger vems inlägg de svarar på. Följ-händelser visar namnet på den som följdes. Du kan också följa jobbet under **Bakgrundsjobb**.
3. Expandera ett **försök** för att se detaljer. **Konfiguration** tar dig tillbaka till tidslinjen.
4. Vid flera varianter växlar du mellan dem med flikarna (huvudspår, A eller B).
5. I översikten:
   - **Nätverk & åtgärder** visar positiv/neutral/negativ fördelning. Ikonen öppnar mer detaljer.
   - **Vanliga fraser** och **Ämnesglidning** sammanfattar mätpunkterna.
   - Resultatet visas som **Flöde** till vänster och **Aktivitet** till höger. Välj **Flöde**, **Aktivitet** eller **Båda**. **Population** (och **Injektorer**) är fällbara listor ovanför flödet — populationen är dold tills du öppnar den. Klicka på en agent för personaprofilen, eller **Intervjua** för att chatta om vad den sett. På klara körningar: stjärnan visar SSR-klassificering, skölden lägger till kommentaren som ankare.
6. Markera minst två försök och välj **Jämför markerade** för att beställa en jämförelserapport. Dokumentikonet beställer rapport för ett enskilt försök.
7. **Radera** tar bort ett enskilt försök efter bekräftelse.

Vid **stimulus vs kontroll**-upplägg visas en jämförelse mellan variant A (med injektion) och B (kontroll utan injektion).

## Relaterade guider

- [Starta en simulering](starta-simulering.md)
- [Beställa en rapport](bestalla-rapport.md)
- [Lägga till SSR-ankare från körning](lagg-till-ssr-ankare-fran-korning.md)
- [Skapa och redigera persona](skapa-och-redigera-persona.md)
