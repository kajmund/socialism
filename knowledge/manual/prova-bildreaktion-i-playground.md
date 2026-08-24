---
type: guide
title: Prova bildreaktion i playground
description: Så testar du hur en persona reagerar på en bild och hur ton och stil klassificeras via SSR.
tags: [grunddata]
---

# Prova bildreaktion i playground

I playground finns en **Bild**-flik där du laddar upp en bild, låter en persona reagera på den, och ser SSR-klassificering av reaktionen — utan att köra en full simulering.

## Steg

1. Logga in som **administratör** och öppna **Verktyg** → **Playground**.
2. Välj fliken **Bild**.
3. Välj **Persona** från biblioteket (du behöver minst en sparad persona).
4. Välj **Bildmodell** (leverantör och modell) och **Reaktionsmodell**.
5. Välj **Språk** för ankare och justera **Temperatur** om du vill (lägre värde ger skarpare SSR-fördelning).
6. Ladda upp en bild (JPEG, PNG, WebP eller GIF).
7. Klicka **Kör**.
8. Granska resultatet:
   - **Bildbeskrivning** — vad modellen ser i bilden.
   - **Reaktion** — personans svar på bilden.
   - **Ton** och **Stil** — SSR-fördelning och förutsagd etikett.

Resultatet sparas inte automatiskt till budskapsbiblioteket eller en körning. Använd det för att kalibrera innan du skapar bildbudskap eller kör simuleringar.

## Relaterade guider

- [Använda playground](anvanda-playground.md)
- [Skapa budskap i verkstaden](skapa-budskap-i-verkstaden.md)
- [Hantera SSR-ankare](hantera-ssr-ankare.md)
