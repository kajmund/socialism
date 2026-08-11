---
type: guide
title: Hantera SSR-ankare
description: Så skapar, testar, publicerar och kopplar du ton- och stilankare för rapporter.
tags: [grunddata]
---

# Hantera SSR-ankare

**SSR-ankare** är versionerade uppsättningar av etiketter och ankartexter som styr hur ton och stil mäts i rapporter. Du bygger och testar ankare i biblioteket, publicerar dem, och väljer sedan vilka som ska gälla i den aktiva konfigurationen.

## Öppna biblioteket

1. Öppna **Verktyg** → **SSR-ankare** i menyn.
2. Filtrera efter **typ** (Ton eller Stil) och **språk** (svenska eller engelska) om du vill begränsa listan.
3. På varje kort ser du namn, typ, språk, version och om posten är **Utkast** eller **Publicerad**.

## Skapa nytt ankare

1. Välj **+ Nytt ankare**.
2. Ange **namn**, **typ** (Ton eller Stil), **språk** och **version**. Typ och språk låses efter att ankaret skapats.
3. På fliken **Ankare** fyller du i par av **etikett** och **ankartext** — en rad per skala (t.ex. fem tonnivåer eller sex stilvarianter).
4. Välj **Spara**. Du landar i redigeringsläget där flikarna **Kalibrering** och **Test** blir tillgängliga.

## Kalibrera och testa

1. På fliken **Kalibrering**: lägg till exempelkommentarer med en **manuell etikett** från skalan. Dessa används för att mäta träffsäkerhet.
2. På fliken **Test**: klistra in kommentarer (en per rad) och kör **SSR-test**, eller kör **Testa kalibrering** mot korpusen du byggt upp.
3. Justera ankartexterna och kör om tills resultatet känns rimligt. Du kan också prova ankare i **Playground** innan du publicerar.

## Publicera och hantera versioner

1. När du är nöjd: gå tillbaka till listan och välj **Publicera** på utkastet.
2. **Publicerade** ankare kan inte redigeras — de är låsta. Välj **Duplicera** för att skapa ett nytt utkast baserat på en publicerad version.
3. **Ta bort** går bara för utkast.
4. Endast **publicerade** ankare kan väljas i en konfiguration.

**Pool på publicerade set:** du kan lägga till och ta bort **simulerade exempel** (pool) direkt på publicerade ankare — de gäller omedelbart för nya rapporter. Själva basraderna (etikett + ankartext) förblir låsta; duplicera setet om du vill ändra dem.

## Koppla till konfiguration

1. Öppna **Verktyg** → **Konfigurationer** och redigera den konfiguration du vill använda.
2. Gå till fliken **SSR-ankare**.
3. Välj publicerat **ton-** och **stilankare** för svenska respektive engelska rapporter, och ställ in **SSR-temperatur** om det behövs.
4. **Spara** konfigurationen och markera den som **Aktiv** om den ska gälla i skarpa rapporter.

## Relaterade guider

- [Hantera konfigurationer](hantera-konfigurationer.md)
- [Använda playground](anvanda-playground.md)
- [Hantera embedding-cache](hantera-embedding-cache.md)
- [Läsa simuleringsrapport](lasa-simuleringsrapport.md)
- [Lägga till SSR-ankare från körning](lagg-till-ssr-ankare-fran-korning.md)
