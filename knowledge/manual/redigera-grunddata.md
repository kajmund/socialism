---
type: guide
title: Redigera grunddata
description: Så hanterar du kataloglistor som personas och populationer bygger på — per konfiguration.
tags: [grunddata]
---

# Redigera grunddata

Grunddata (kataloglistor) hör till en **konfiguration** tillsammans med promptinställningarna. Den **aktiva** konfigurationens listor fyller dropdowns i hela appen — t.ex. kön, distrikt, yrke, ton och partisympati.

## Steg

1. Öppna **Konfigurationer** i menyn och **Redigera** den konfiguration du vill ändra.
2. Välj fliken **Grunddata** (bredvid **Promptinställningar**).
3. Välj sektion: **Demografi**, **Politik**, **Värderingar**, **Röst & media**, **Simulering** eller **DD expertpanel**.
4. Välj den lista du vill redigera (t.ex. **Distrikt**, **Ton**, **Parti** eller **Expertroller**).
5. **Lägg till**, **redigera**, **ändra ordning** eller **ta bort** rader i listan.
6. Välj **Spara** när du gjort ändringar (osparda ändringar markeras).

Ny konfiguration: spara först namn och prompts — då skapas grunddatalistorna och fliken **Grunddata** blir tillgänglig.

## DD expertpanel

Under **DD expertpanel** → **Expertroller** konfigurerar du rollerna som due diligence-panelen kan använda (namn, beskrivning, kompetens, stil, bakgrund och anekdot). Bolag-användare redigerar samma lista via menyn **Experter** i Due diligence-ytan — se [Konfigurera DD-experter](konfigurera-dd-experter.md).

## Distrikt med karta

För listan **Distrikt** kan du dessutom:

1. Redigera distriktets namn och beskrivning.
2. Välj **Sätt område på karta** eller **Redigera karta** för att rita geografiska gränser på kartan.
3. Spara listan när du är klar.

Ändringar i grunddata påverkar nya personas och populationer när konfigurationen är aktiv — befintliga sparade värden behåller sina etiketter tills de redigeras.

**Ton** och **förtroende** kommer bara härifrån. När du genererar en population samplas röst och förtroende från de här listorna — det finns ingen extra hårdkodad ton vid sidan av. Sarkastisk eller cynisk röst dyker bara upp om du har de etiketterna i listan och receptet väger in dem.

## Relaterade guider

- [Hantera konfigurationer](hantera-konfigurationer.md)
- [Konfigurera DD-experter](konfigurera-dd-experter.md)
- [Skapa och redigera persona](skapa-och-redigera-persona.md)
- [Bygga en population](bygga-population.md)
