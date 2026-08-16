---
type: guide
title: Lägga till SSR-ankare från körning
description: Tagga kommentarer från avslutade simuleringar som ton- och stilankare.
tags: [korningar, rapporter, grunddata]
---

# Lägga till SSR-ankare från körning

När en simulering är **klar** kan du plocka ut kommentarer från flödet och lägga till dem i SSR-ankarbiblioteket. Det gör att framtida rapporter kan grundas mer i faktiskt simulerat språk, inte bara i forskartexterna basankare.

## Var du hittar funktionen

1. Öppna körningen via **Öppna resultat**.
2. Expandera ett sparat försök (och rätt variant om du körde A/B).
3. I **flödet** har varje kommentar en sköld — **Lägg till som SSR-ankare**.

Skölden visas bara när körningen har status **Klar**.

Guldmärkena i rutan visar vilket **ton-** och **stilset** den aktiva konfigurationen använder.

## Så lägger du till en kommentar

1. Klicka på skölden vid kommentaren.
2. I rutan ser du texten, systemets klassificering (om den finns) och de aktiva ankarseten.
3. Välj **ton** och/eller **stil**. Tomt val är **Ingen**.
4. Kryssa i **Lägg även till i kalibrering** om du vill att samma text ska finnas i testkorpusen i ankareditorn (valfritt).
5. Klicka **Lägg till ankare**.

Ankare blir **direkt aktiva** i det ankarbibliotek som den **aktiva konfigurationen** pekar på för körningens språk.

## Fel klassificering

Om SSR:s förslag är fel: klicka på stjärnan vid kommentaren, välj **Rapportera fel klassificering** och ange rätt etikett.

Flaggningen hamnar under fliken **Flaggade** i respektive ankarset, där du senare kan **lägga till som ankare** eller **avfärda**.

## Ta bort ankare

Taggade exempel tas bort under fliken **Ankarpool** i ankareditorn.

Grundankartexterna (forskartexterna basrader) i biblioteket kan fortfarande inte redigeras — bara pool-tillägg på publicerade set.

## Relaterade guider

- [Hantera SSR-ankare](hantera-ssr-ankare.md)
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
- [Läsa simuleringsrapport](lasa-simuleringsrapport.md)
