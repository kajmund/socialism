---
type: guide
title: Hantera kundprodukt och moduler
description: Så väljer du GUI-produkt och slår på eller av moduler för varje kund under Verktyg.
tags: [grunddata]
---

# Hantera kundprodukt och moduler

Ytan **Verktyg** → **Kunder** syns bara för **administratör**.

Varje kund har en uppsättning **tillgängliga moduler** (till exempel politisk simulering, Due Diligence, Expertgranskning och Rättsunderlag). Det styr vilka ytor inloggningen öppnar, vilka länkar som syns i vänstermenyn och vilka rapportflikar som visas — inte bara inloggningsrollen.

Kunden kan också ha en **produkt**. Produkten styr hela gränssnittet och är skild från modulerna. **Standard** använder den vanliga adminytan. **SME** ersätter adminytan med SME-chatten; modulerna kan fortfarande användas under huven men visas inte i någon modulmeny.

**Administratör** ser alltid **Expertgranskning** och **Rättsunderlag** i vänstermenyn, även om rutan inte är ikryssad för någon kund. Klick på **Due Diligence** (Kampanjer) byter yta men tar inte bort de andra menyvalen. En inloggning som bara har Due Diligence ser bara den modulens länkar. Rubriken för en avstängd modul visas inte.

## Steg

1. Öppna **Verktyg** → **Kunder**.
2. I tabellen syns kundens namn, slug, produkt och en kryssruta per modul.
3. Välj **Standard** eller **SME** i produktlistan.
4. Kryssa i eller ur moduler. Varje ändring sparas direkt.
5. Logga in på nytt (eller ladda om) för att se det valda gränssnittet.

En kund utan kryssade moduler får inga modulflikar i rapporterna och kan inte komma in i någon modul-yta. Ta inte bort sista modulen för en kund som ska fortsätta arbeta i ytan.

## Relaterade guider

- [Logga in](logga-in.md)
- [Redigera panelkatalog](redigera-panelkatalog.md)
- [Hantera rapporter](hantera-rapporter.md)
- [Översikt av ytorna](oversikt.md)
