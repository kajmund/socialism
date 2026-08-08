---
type: guide
title: Använda playground
description: Så kalibrerar du anchors, jämför SSR mot nyckelord, provar promptvarianter och testar agentverktyg innan skarpa körningar.
tags: [grunddata]
---

# Använda playground

**Playground** är ett adminverktyg för att testa och jämföra innan du litar på resultatet i skarpa rapporter eller konfigurationer. Ändringar här sparas inte automatiskt tillbaka till konfigurationer eller produktionsankare.

## Steg

1. Öppna **Verktyg** → **Playground** i menyn.
2. Välj flik efter vad du vill göra:
   - **Anchor-kalibrering** — redigera ankarpåståenden, klistra in testmeningar (en per rad) och kör SSR. Justera **temperatur** (lägre skärper fördelningen; default 0,1). Valfritt: sätt en mänsklig etikett per mening och se träfffrekvens.
   - **Prompt-iteration** — välj en **konfiguration** och en **promptnyckel**, redigera variant B, fyll i platshållare och kör A och B sida vid sida via DeepSeek.
   - **SSR vs nyckelord** — samma testmeningar genom SSR (ton) och nyckelordsmetoden, så du ser var de skiljer sig. Samma temperaturinställning gäller här.
   - **Agentverktyg** — kör webbsök (DuckDuckGo/Wikipedia) eller SymPy med samma funktioner som du kan knyta till en körning, utan en full simulering.
3. Tolka resultatet i tabellen eller andelarna — justera ankartexter eller promptvariant och kör om tills det känns rätt.
4. När du är nöjd med en prompt: kopiera den till **Konfigurationer** och spara där. Anchor-defaults i skarpa rapporter ändras inte från playground i det här läget.

## Relaterade guider

- [Hantera konfigurationer](hantera-konfigurationer.md)
- [Läsa simuleringsrapport](lasa-simuleringsrapport.md)
- [Översikt av ytorna](oversikt.md)
