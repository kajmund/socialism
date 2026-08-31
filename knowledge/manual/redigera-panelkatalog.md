---
type: guide
title: Redigera panelkatalog
description: Så lägger du till och redigerar sub-frågor och default-expertprofiler för expertpanelen.
tags: [grunddata]
---

# Redigera panelkatalog

Ytan **Verktyg** → **Panelkatalog** syns bara för **administratör**.

Här redigerar du **sub-frågor** (bedömningsdimensioner, unika per modul) och **default-expertprofiler**. En expertprofil kan tillhöra flera moduler — samma rad, inte en kopia. Ändringar gäller nästa panelkörning. Pågående eller avslutade körningar ändras inte.

## Steg

1. Öppna **Verktyg** → **Panelkatalog**.
2. Välj **modul** (due diligence i dag).
3. Under **Sub-frågor**: ändra etikett eller ordning och klicka **Spara**. **Ordning** måste vara unik — två rader får inte dela nummer. För att byta plats, flytta den ena till ett ledigt nummer först. Avmarkera **Aktiv** för att dölja dimensionen i nya körningar utan att ta bort den.
4. Lägg till en ny sub-fråga med **nyckel** (gemener, siffror och understreck) och **etikett**. Nyckeln går inte att ändra efteråt.
5. Under **Default-expertprofiler**: redigera namn, beskrivning, bakgrund och ordning och klicka **Spara**. Ordningen är global (samma lista oavsett modul). Avmarkera **Aktiv** för att sluta seeda den profilen.
6. **Lägg till expertprofil** skapar en ny rad. Nyckeln skapas från namnet.

Ta inte bort rader i databasen — inaktivera dem i stället.

## Relaterade guider

- [Komponera en expertpanel](komponera-expertpanel.md)
- [Köra en DD-kampanj](kora-dd-kampanj.md)
- [Hantera kundmoduler](hantera-kundmoduler.md)
