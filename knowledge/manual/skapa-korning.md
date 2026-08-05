---
type: guide
title: Skapa en ny körning
description: Så konfigurerar du en ny körning med population, tidslinje och gren.
tags: [korningar]
---

# Skapa en ny körning

En **körning** beskriver scenariot du vill testa: vilken population som deltar, vilka budskap som injiceras över tid, och om du jämför två varianter.

## Steg

1. Öppna **Körningar** och välj att skapa ny.
2. Fyll i **grunduppgifter**: namn, population och startdatum.
3. Bygg **tidslinjen**: lägg till dagar/tick, injektioner (text eller budskap från biblioteket) och antal reaktionsrundor.
4. Välj eventuellt en **gren** efter en delad stam:
   - **A/B** — två formuleringar av budskapet
   - **Stimulus/kontroll** — en variant med stimulus, en utan injektion
5. Granska sammanfattningen och spara.

Du kan också använda snabbläge om du vill hoppa över den stegvisa guiden.

## Obs

- Minst en tick krävs.
- Tick utan ny injektion kan vara **tysta** — populationen reagerar ändå i simuleringen.
- Budskap från biblioteket låses in i körningen när du senare startar simuleringen.

## Relaterade guider

- [Översikt av ytorna](oversikt.md)
- [Starta en simulering](starta-simulering.md)
