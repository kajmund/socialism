---
type: guide
title: Läsa simuleringsrapport
description: Så öppnar och läser du en färdig HTML-rapport från en simulering.
tags: [rapporter]
---

# Läsa simuleringsrapport

När en rapport har genererats öppnas den som en **HTML-sida** i appen. Alla rapporter finns under menyn **Rapporter**. Nya rapporter beställs från simuleringsresultat.

Rapporten börjar med **Slutsats**: vilken version som rekommenderas (vid A/B), om budskapet bör publiceras eller justeras, simulerat stöd (0–100), mottagande och korta styrkor/risker. Direkt under slutsatsen förklaras **vad ton-siffrorna mäter**: **reaktioner på ämne** (kommentarer på injektionsinlägget, medborgarinlägg som fortfarande handlar om testbudskapet, och svar i sådana trådar) vs **ämnesglidning** (inlägg och trådar som lämnar testämnet). Kommentarer på injektionsinlägget räknas alltid som på ämne; kommentarer på ett glidit inlägg följer glidningen utan att räknas som en extra glidning. Ton, stil och mottagande-verdikt bygger bara på reaktioner på ämne; ämnesglidning syns i eget avsnitt med staplar, i engagemang/opinionsledare och som tagg på citat. Därefter följer statistik, diagram, dag-för-dag, målgrupper och vid behov A/B-jämförelse. **Målgruppssammanfattning** (regelbaserade stycken om t.ex. livssituation eller kön) styrs av egna trösklar i konfigurationen — inte samma som slutsats eller rekommendation. Förklaringar till stjärnmarkörer (`*`, `**`, …) står direkt under respektive avsnitt — du behöver inte bläddra till slutet. Öppna **Tekniskt stycke** längst ner för SSR-fördelningar, **sampling** (hur reaktionstexter valts för ton/stil), tröskelvärden och vilken konfiguration som gällde. Trösklarna kommer från aktiv konfiguration och sparas i `report.ssr.json` per rapport.

## Så läser du siffrorna

- **Engagemang i debatten** räknar bara simulerade medborgare. Institutionella konton (partikonto, nyhetskanal) står utanför och redovisas separat i underrubriken, så samma körning kan visa fler agenter i simuleringsresultatet än medborgare i rapporten. Ringens tre delar summerar alltid till antalet medborgare i rubriken.
- **Andel reaktioner per budskapsstil** visar hur de klassade reaktionerna fördelar sig över stilar — det är alltså inte likes per stil. `0 %` betyder att ingen reaktion liknade stilen i underlaget, inte att stilen fick dåligt mottagande.
- Vid flera körningar visas genomsnitt per körning. Med tre körningar är siffrorna en tendens, inte statistik.

## Steg

1. Öppna rapporten via **Rapporter** i huvudmenyn, länken i **Bakgrundsjobb**, eller notifieringen efter beställning.
2. Medan rapporten **genereras** uppdateras sidan automatiskt.
3. Vid **fel** visas felmeddelandet — gå tillbaka till körningen och försök beställa igen om det behövs.
4. När rapporten är **klar** visas innehållet i sidan.
5. Välj **Öppna i ny flik** om du vill läsa rapporten i ett eget fönster.
6. Länken **← Rapporter** tar dig tillbaka till rapportlistan.

## Relaterade guider

- [Hantera rapporter](hantera-rapporter.md)
- [Beställa en rapport](bestalla-rapport.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
