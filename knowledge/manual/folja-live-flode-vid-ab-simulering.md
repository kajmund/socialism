---
type: guide
title: Följa live-flöde vid A/B-simulering
description: Så följer du simuleringen i realtid och växlar mellan version A och B medan jobbet körs.
tags: [korningar]
---

# Följa live-flöde vid A/B-simulering

När en simulering **körs** kan du öppna **Resultat** och följa **Live-flöde** innan jobbet är klart. Har körningen två varianter (A/B eller stimulus/kontroll) uppdateras **båda spåren parallellt** — samma population, men olika injektioner från grenpunkten eller från start om du valde **A/B från start**.

## Öppna live-vyn

1. Starta simuleringen från körningen (se [Starta en simulering](starta-simulering.md)).
2. Öppna körningen och gå till fliken **Resultat** medan status är **Pågår**.
3. Överst syns **Live-flöde** med statusrad (ansluter, väntar, pågår eller avslutades).
4. Växla layout med **Flöde**, **Aktivitet** eller **Båda** — samma val som efter avslutad körning (se [Läsa simuleringsresultat](lasa-simuleringsresultat.md)).

## Växla variant medan simuleringen pågår

1. Om körningen har mer än en variant visas flikar till höger om live-rubriken (till exempel **Version A** och **Version B**, eller stimulus/kontroll-etiketter).
2. Välj en flik — flödet och aktiviteten visar **den varianten** i realtid.
3. Byt flik när du vill jämföra hur de två uppläggen utvecklas **samtidigt** under samma jobb.

Live-flödet ansluter per variant. Misslyckas en variant visas det i statusraden för den fliken.

## När båda varianter körs från start

Valde du **Starta A/B från början** i tidslinjen delar A och B samma population från dag ett, men injektionerna skiljer sig från första tick. Simuleringen kör **båda grenarna parallellt** — du behöver inte vänta på att ena varianten ska bli klar innan den andra börjar.

Tidslinjen visar att version A och B körs parallellt från start. Live-flödets variantflikar motsvarar samma två spår.

## Efter simuleringen

När jobbet är klart laddas sparade försök in. Variantflikarna finns kvar på resultatet tillsammans med översikt, nätverk och rapportbeställning — se [Läsa simuleringsresultat](lasa-simuleringsresultat.md).

## Relaterade guider

- [Skapa en ny körning](skapa-korning.md)
- [Starta en simulering](starta-simulering.md)
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
- [Reaktionsmodell i simuleringen](reaktionsmodell-i-simulering.md)
