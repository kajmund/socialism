---
type: guide
title: Läsa simuleringsrapport
description: Så öppnar och läser du en färdig HTML-rapport från en simulering.
tags: [rapporter]
---

# Läsa simuleringsrapport

När en rapport har genererats öppnas den som en **HTML-sida** i appen. Alla rapporter finns under menyn **Rapporter**. Nya rapporter beställs från simuleringsresultat.

Rapporten börjar med **Slutsats**: vilken version som rekommenderas (vid A/B), om budskapet bör publiceras eller justeras, simulerat stöd (0–100), mottagande och korta styrkor/risker. Därefter följer statistik, diagram, dag-för-dag, målgrupper och vid behov A/B-jämförelse. Förklaringar till stjärnmarkörer (`*`, `**`, …) står direkt under respektive avsnitt — du behöver inte bläddra till slutet. Öppna **Tekniskt stycke** längst ner för SSR-fördelningar, **sampling** (hur reaktionstexter valts för ton/stil), tröskelvärden och vilken konfiguration som gällde. Trösklarna kommer från aktiv konfiguration och sparas i `report.ssr.json` per rapport.

## Steg

1. Öppna rapporten via **Rapporter** i huvudmenyn, länken i **Bakgrundsjobb**, eller notifieringen efter beställning.
2. Medan rapporten **genereras** uppdateras sidan automatiskt.
3. Vid **fel** visas felmeddelandet — gå tillbaka till körningen och försök beställa igen om det behövs.
4. När rapporten är **klar** visas innehållet i sidan.
5. Under rapporten kan du **bedöma slutsatsen** (verdict-kalibrering): ange om rekommendationen t.ex. «Redo att publicera» stämmer med hela rapporten, och spara en valfri kommentar.
6. Välj **Öppna i ny flik** om du vill läsa rapporten i ett eget fönster.
7. Länken **← Rapporter** tar dig tillbaka till rapportlistan.

## Relaterade guider

- [Hantera rapporter](hantera-rapporter.md)
- [Beställa en rapport](bestalla-rapport.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
