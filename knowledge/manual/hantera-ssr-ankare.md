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
3. Växla mellan **Rutnät** och **Lista**.
4. På varje kort ser du namn, typ, språk, version och om posten är **Utkast** eller **Publicerad**.

## Etikettordlista

Etiketter för ton och stil delas mellan alla ankarset av samma typ och språk.

1. Välj **Etikettordlista** ovanför listan.
2. Byt namn på en etikett för att uppdatera den överallt den används (även i pool och kalibrering).
3. Lägg till nya etiketter eller ta bort sådana som inte används.
4. Stäng panelen när du är klar.

## Skapa nytt ankare

1. Välj **+ Nytt ankarset**.
2. Ange **namn**, **typ** (Ton eller Stil), **språk** och **version**. Typ och språk låses efter att ankaret skapats.
3. På fliken **Ankare** väljer du **etikett** från ordlistan och fyller i **referensmening** — en rad per steg på skalan.
4. Välj **Spara**. Du landar i redigeringsläget där flikarna **Kalibrering**, **Test**, **Ankarpool** och **Flaggade** blir tillgängliga.

## Kalibrera, testa och pool

1. På fliken **Kalibrering**: lägg till exempelkommentarer med en **manuell etikett** från skalan. Dessa används för att mäta träffsäkerhet.
2. På fliken **Test**: klistra in kommentarer (en per rad) och kör **SSR-test**, eller kör **Testa kalibrering** mot korpusen du byggt upp.
3. På fliken **Ankarpool**: granska taggade exempel från körningar — sök, filtrera på etikett och ta bort vid behov.
4. På fliken **Flaggade**: granska texter som operatörer har markerat som felklassificerade i körningsresultat. **Lägg till som ankare** eller **Avfärda**.
5. Justera referensmeningarna och kör om tills resultatet känns rimligt. Du kan också prova ankare i **Playground** innan du publicerar.

## Publicera och hantera versioner

1. Lägg till **minst åtta** kalibreringsrader på fliken Kalibrering och kör **Kör och spara kalibreringstest** (macro-träff per etikett, mål ≥55 %).
2. När du är nöjd: gå tillbaka till listan och välj **Publicera** på utkastet. Publicering blockeras om kalibreringen är otillräcklig — du kan bekräfta och publicera ändå vid varning (t.ex. låg träff eller saknade etiketter).
3. **Publicerade** ankare kan inte redigeras — basraderna (etikett + referensmening) är låsta. Välj **Duplicera** för att skapa ett nytt utkast baserat på en publicerad version.
4. **Ta bort** går bara för utkast.
5. Endast **publicerade** ankare kan väljas i en konfiguration.

**Pool på publicerade set:** du kan lägga till och ta bort **simulerade exempel** (pool) direkt på publicerade ankare — de gäller omedelbart för nya rapporter och markerar kalibreringen som **inaktuell** tills du kör om testet. Själva basraderna förblir låsta; duplicera setet om du vill ändra dem.

**Rapporter:** om aktiva ankare är otestade, inaktuella eller under tröskeln visas en varning högst upp i snabbrapporten (rapporten genereras ändå).

## Koppla till konfiguration

1. Öppna **Verktyg** → **Konfigurationer** och redigera den konfiguration du vill använda.
2. Gå till fliken **Ankare** för att välja publicerat ton- och stilankare per språk.
3. Under **Känslighet & rapportgränser** ställer du in SSR-temperatur och rapporttrösklar.
4. **Spara** konfigurationen och markera den som **Aktiv** om den ska gälla i skarpa rapporter.

## Relaterade guider

- [Hantera konfigurationer](hantera-konfigurationer.md)
- [Använda playground](anvanda-playground.md)
- [Hantera embedding-cache](hantera-embedding-cache.md)
- [Läsa simuleringsrapport](lasa-simuleringsrapport.md)
- [Lägga till SSR-ankare från körning](lagg-till-ssr-ankare-fran-korning.md)
