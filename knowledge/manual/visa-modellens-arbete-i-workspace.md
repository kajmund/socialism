---
type: guide
title: Visa modellens arbete i workspace
description: Så följer du verktygsanrop och mellansteg medan experten svarar i SME-workspace.
tags: [grunddata, jobb]
---

# Visa modellens arbete i workspace

I **SME** och i expertens **Workspace-chatt** kan du se vad modellen gör bakom svaren — vilken kontext som skickades, vilka verktyg som anropades och vad de returnerade. Det hjälper dig förstå varför ett svar tog tid eller vilka källor som användes, utan att läsa tekniska loggar.

## Öppna vyn

1. Öppna **Workspace** bredvid chatten (i SME: växla till **Workspace** på en liten skärm).
2. I flikraden ovanför arbetsytan — **Evidens**, **Dokument**, **Jämförelse**, **Relationer** — finns en ikon längst till höger (**Modellens arbete**).
3. Välj ikonen. En dialog öppnas med en kronologisk lista över händelser för den aktuella expertchatten.

Listan uppdateras medan experten tänker, anropar verktyg och skriver svar. Tom lista betyder att inget har loggats ännu i den här konversationen.

## Tolka raderna

Varje rad har en typ och kort text:

- **Kontext** — sammanfattning av vad som skickades in till modellen.
- **Meddelande** — mellanliggande resonemang eller intern text (inte alltid samma som det slutliga chatsvaret).
- **Verktyg** — att verktyg är tillgängliga eller att ett verktygssteg pågår.
- **Verktygsanrop** — vilket verktyg som kördes och med vilka argument.
- **Verktygsresultat** — vad verktyget returnerade.

Rader som gäller verktyg markeras med en tydligare kant så att du snabbt ser när experten till exempel läste ett dokument, startade research eller öppnade en vy.

## Källnummer i chatten

När svaret citerar underlag visas **numrerade knappar** i texten (t.ex. guldmarkerade siffror). Välj ett nummer för att öppna motsvarande källa i workspace — ofta rätt sida i PDF:en eller evidensvyn. Saknas källan längre visas en varning vid numret i stället för en länk.

Detta är samma referensnummer som du kan se samlade under **Evidens**.

## Obs

- Vyn gäller den **valda** expertchatten. Byter du expert eller panel börjar listan om för den tråden.
- Innehållet är till för transparens vid felsökning och uppföljning — du behöver inte läsa det för att använda chatten normalt.

## Relaterade guider

- [Använda SME-chatten](anvanda-sme-chatten.md)
- [Använda workspace-chatten](anvanda-workspace-chatten.md)
- [Följa research i realtid](folja-research-i-realtid.md)
