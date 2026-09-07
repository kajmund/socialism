---
type: guide
title: Konfigurera panelkatalog för Expertgranskning
description: Så redigerar du sub-frågor och default-expertprofiler för expertgranskningens panelmotor.
tags: [grunddata]
---

# Konfigurera panelkatalog för Expertgranskning

**Panelkatalogen** styr vilka **sub-frågor** (bedömningsdimensioner) och **default-expertprofiler** som panelmotorn använder. Due Diligence och **Expertgranskning** delar samma verktyg men har **egna sub-frågor per modul**.

Ytan **Verktyg** → **Panelkatalog** syns bara för **administratör**.

## Välj modul

1. Öppna **Verktyg** → **Panelkatalog**.
2. Välj **Expertgranskning** i modullistan (bredvid Due Diligence om båda är aktiva).
3. Sub-frågorna du ser gäller bara expertgranskning — inte Due Diligence-panelen.

## Sub-frågor

1. Under **Sub-frågor**: ändra etikett eller ordning och klicka **Spara**.
2. **Ordning** måste vara unik — flytta till ledigt nummer om du byter plats.
3. **Ta bort** fungerar bara om frågan inte används i någon körning eller rapport.
4. Lägg till ny sub-fråga med **nyckel** (gemener, siffror, understreck) och **etikett**. Nyckeln låses efter skapande.

Ändringar gäller **nästa** expertgranskning. Pågående eller avslutade körningar ändras inte.

## Default-expertprofiler

Default-profilerna är **gemensamma** för alla moduler med panelmotor — samma lista oavsett om du står på Due Diligence eller Expertgranskning.

1. Redigera namn, beskrivning, bakgrund och ordning under **Default-expertprofiler**.
2. Avmarkera **Aktiv** för att sluta seeda profilen i nya paneler.
3. **Lägg till expertprofil** skapar en ny rad.

För att skapa riktiga experter i biblioteket, se [Hantera experter](hantera-experter.md) och **Föreslå experter**.

## Relaterade guider

- [Redigera panelkatalog](redigera-panelkatalog.md) — samma yta, fokus Due Diligence
- [Använda expertgranskning](anvanda-expertgranskning.md)
- [Hantera expertpaneler](hantera-expertpaneler.md)
- [Hantera kundmoduler](hantera-kundmoduler.md)
