---
type: guide
title: Beställa en rapport
description: Så skapar du en sammanfattnings- eller jämförelserapport från simuleringsresultat.
tags: [rapporter, korningar]
---

# Beställa en rapport

Från simuleringsresultat kan du beställa en **HTML-rapport** som sammanfattar ett försök eller jämför flera. Du väljer mellan **Snabbrapport** och **Full rapport**.

## Steg

1. Öppna körningen och gå till fliken **Resultat**.
2. För **en** simulering: välj **Beställ rapport** på det försök du vill sammanfatta.
3. För **jämförelse**: markera två eller fler försök med kryssrutor och välj **Jämför i rapport**.
4. Välj läge:
   - **Snabbrapport** — snabb mallbaserad sammanfattning (verdict, ämnesdrift, stil, A/B) via embeddings. Ingen AI-prosa. Passar när du vill iterera över budskapsvarianter.
   - **Full rapport** — längre hybridrapport med diagram och AI-skriven prosa. Tar flera minuter.
5. Bekräfta att genereringen ska starta.
6. Rapporten skapas som ett bakgrundsjobb — följ status under **Bakgrundsjobb** eller vänta på notifieringen.
7. När rapporten är klar öppnas den automatiskt, eller nå den via länken i jobblistan.

Se [Läsa simuleringsrapport](lasa-simuleringsrapport.md) för hur du läser den färdiga rapporten. För snabbrapportens tekniska detaljer, öppna **Tekniskt stycke** längst ner i rapporten.

## Relaterade guider

- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
- [Läsa simuleringsrapport](lasa-simuleringsrapport.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
