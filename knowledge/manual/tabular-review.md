---
type: guide
title: Använda Tabular Review
description: Jämför avtal mot SSR-kategorier i en tabell och granska klausuler i originaldokumentet.
tags: [grunddata]
---

# Använda Tabular Review

**Tabular Review** är en egen yta i vänstermenyn. Den syns bara när kunden har modulen påslagen under **Verktyg** → **Kunder**. Tabellen fylls med likhet mot sparade klausulankare — inte med en språkmodell.

Varje rad är ett avtal. Varje kolumn är en kategori (till exempel uppsägningstid eller pris). Cellen visar den **ordagranna klausulen** och ett **similarity**-värde, inte en procentsannolikhet.

## Hantera sparade reviews

1. På listan öppnar du en sparad review genom att klicka på namnet.
2. Varje rad visar hur många avtal och kolumner som ingår samt när reviewn senast uppdaterades.
3. **Ta bort** raderar reviewn. Avtalen i underlaget påverkas inte.

## Skapa en review

1. Öppna **Tabular Review** och välj **Ny review**.
2. Ge reviewn ett namn och spara.
3. Bocka för de avtal som ska ingå.
4. Lägg till kolumner från en **aktiv klausulkategori** som redan finns för kunden (byggs med **Verktyg** → **Klausulankare** och **SSR-ankare**, typ **Klausul**). Saknas kategorier i listan måste ankarna verifieras och aktiveras först — se [Granska klausulankare](granska-klausulankare.md) och [Hantera SSR-ankare](hantera-ssr-ankare.md).
5. Justera **scoregränsen** om du vill kräva högre eller lägre likhet.
6. Välj **Fyll tabellen**.
7. Lägg till eller ta bort **kolumner** när som helst: välj kategori från klausulankarset, ange rubrik och **Lägg till kolumn**, eller **Ta bort kolumn** på en befintlig kolumn.
8. Använd **Sök** och **Statusfilter** ovanför tabellen för att hitta rader eller celler med till exempel träff, ingen träff eller osäker.

## Läsa tabellen

- Klicka på rubriken **Avtal** eller på en kolumnrubrik för att sortera efter avtalsnamn eller efter similarity i den kolumnen.
- **Träff** visar klausulen och similarity.
- **Ingen träff** betyder inte automatiskt att klausulen saknas i avtalet. Under statusen kan en orsak visas:
  - **Låg likhet** — bästa kandidat låg under scoregränsen.
  - **Inga aktiva ankare** — kolumnen saknar aktiva ankare att matcha mot.
  - **Inga kandidater** — inga klausuler hittades att jämföra.
  - **Osäker marginal** — två kandidater låg för nära varandra (statusen blir då ofta **Osäker** i stället).
- **Osäker** visas när två kandidater ligger för nära varandra.
- **Negativ träff** används för kolumner som letar efter motexempel.

Klicka på en cell för **Review Mode**: resultatet till vänster och dokumentet till höger. Finns ingen exakt markering öppnas sidan eller klausulhänvisningen som finns i källan. Finns flera kandidater kan du välja **Fler kandidater**.

## Granska en cell

- **Godkänn match** eller **Avvisa match** sparar en mänsklig kontroll för just den kategorin och den klausulen. Det lägger inte automatiskt till ett SSR-ankare.
- **Flagga** markerar cellen för senare genomgång.
- **Lås** skyddar cellen så att en ny ifyllning inte skriver över den.
- **Anteckning** sparas på cellen. **Ändringshistorik** listar godkännanden, flaggor, låsningar och anteckningar med vem som gjorde vad.
- **Ta bort flagga** och **Lås upp** tar bort markeringen utan att ändra själva matchningen.

## Relaterade guider

- [Granska klausulankare](granska-klausulankare.md)
- [Hantera SSR-ankare](hantera-ssr-ankare.md)
