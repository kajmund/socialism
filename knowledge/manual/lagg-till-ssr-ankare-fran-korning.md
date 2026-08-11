---
type: guide
title: Lägga till SSR-ankare från körning
description: Tagga kommentarer och intervjusvar från avslutade simuleringar som ton- och stilankare.
tags: [korningar, rapporter, grunddata]
---

# Lägga till SSR-ankare från körning

När en simulering är **klar** kan du plocka ut riktiga kommentarer och intervjusvar från resultatet och lägga till dem i SSR-ankarbiblioteket. Det gör att framtida rapporter kan grundas mer i faktiskt simulerat språk, inte bara i forskartexterna basankare.

## Var du hittar funktionen

1. Öppna körningen och gå till fliken **Resultat**.
2. Expandera ett sparat försök (och rätt variant om du körde A/B).
3. Scrolla till avsnittet **SSR-ankare från körningen** under flödet.

Avsnittet visas bara när körningen har status **Klar** och det finns sparade resultat.

## Vilka texter som visas

| Typ | Källa |
| --- | --- |
| **Kommentar** | Flödeskommentarer från simuleringen |
| **Planerad intervju** | Tick-intervjuer som kördes via OASIS under simuleringen |
| **Intervju i efterhand** | Svar från post-hoc-intervjuer du gjort mot personas efter körningen |

## Så taggar du en rad

1. Läs texten och välj **ton** och/eller **stil** i listorna. Du kan välja båda — då skapas ett ankare i respektive bibliotek.
2. Kryssa i **Lägg även till i kalibrering** om du vill att samma text ska finnas i testkorpusen i ankareditorn (valfritt).
3. Klicka **Lägg till som ankare**.

Ankare blir **direkt aktiva** i det ankarbibliotek som den **aktiva konfigurationen** pekar på för körningens språk. Ton- och stilset namn visas ovanför listan så du ser vart texterna hamnar.

## Ta bort ankare

Om en rad redan är tillagd visas små etiketter under ton/stil. Klicka på **×** för att ta bort just den pool-posten.

Grundankartexterna (forskartexterna basrader) i biblioteket kan fortfarande inte redigeras — bara pool-tillägg på publicerade set.

## Relaterade guider

- [Hantera SSR-ankare](hantera-ssr-ankare.md)
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
- [Läsa simuleringsrapport](lasa-simuleringsrapport.md)
