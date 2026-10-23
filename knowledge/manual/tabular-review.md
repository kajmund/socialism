---
type: guide
title: Använda Tabular Review
description: Jämför avtal mot SSR-kategorier i en tabell och granska klausuler i originaldokumentet.
tags: [grunddata]
---

# Använda Tabular Review

**Tabular Review** är en egen yta i vänstermenyn. Den syns bara när kunden har modulen påslagen under **Verktyg** → **Kunder**. Tabellen fylls med likhet mot sparade klausulankare — inte med en språkmodell.

Varje rad är ett avtal. Varje kolumn är en kategori (till exempel uppsägningstid eller pris). Cellen visar den **ordagranna klausulen** och ett **similarity**-värde, inte en procentsannolikhet.

## Skapa en review

1. Öppna **Tabular Review** och välj **Ny review**.
2. Ge reviewn ett namn och spara.
3. Bocka för de avtal som ska ingå.
4. Lägg till kolumner från ett **klausulankarset** (skapas under **Verktyg** → **SSR-ankare**, typ **Klausul**).
5. Justera **scoregränsen** om du vill kräva högre eller lägre likhet.
6. Välj **Fyll tabellen**.

## Läsa tabellen

- **Träff** visar klausulen och similarity.
- **Ingen träff** betyder att ingen kandidat nådde gränsen. Det betyder inte att klausulen saknas i avtalet.
- **Osäker** visas när två kandidater ligger för nära varandra.
- **Negativ träff** används för kolumner som letar efter motexempel.

Klicka på en cell för **Review Mode**: resultatet till vänster och dokumentet till höger. Finns ingen exakt markering öppnas sidan eller klausulhänvisningen som finns i källan.

## Granska en cell

- **Godkänn match** eller **Avvisa match** sparar en mänsklig kontroll för just den kategorin och den klausulen. Det lägger inte automatiskt till ett SSR-ankare.
- **Flagga** markerar cellen för senare genomgång.
- **Lås** skyddar cellen så att en ny ifyllning inte skriver över den.
- **Anteckning** sparas på cellen. Historiken visar vem som gjorde vad.
