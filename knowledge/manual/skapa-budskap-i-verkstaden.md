---
type: guide
title: Skapa budskap i verkstaden
description: Så skriver, sammanfattar och genererar varianter av budskap — inklusive bild-only och bild + text.
tags: [budskap]
---

# Skapa budskap i verkstaden

**Budskapsverkstaden** är där du skriver och sparar innehåll till biblioteket — text, bild, eller båda. Materialet kan injiceras i simuleringar som partiposter, nyheter eller reklam.

## Innehållsläge

Under **Innehåll** väljer du ett av tre lägen:

| Läge | När |
| ---- | --- |
| **Endast text** | Klassiskt budskap eller nyhet — skriv eller hämta från länk |
| **Endast bild** | Politisk reklam eller annons utan följtext — t.ex. en affisch i flödet |
| **Bild + text** | Bild med tillhörande brödtext ovanför eller bredvid i simuleringen |

## Bilder och caption

När du laddar upp en bild:

1. Systemet **cachar** filen med en **SHA256-nyckel** (samma fil ger alltid samma nyckel).
2. En **vision-caption** genereras automatiskt första gången — en rik beskrivning av motiv, text, färger och symboler.
3. Captionen **delas** mellan alla inlägg som använder samma bild. Alla agenter som ser budskapet i simuleringen får samma caption i flödet.

Du kan **redigera caption** i verkstaden. Ändringen sparas i cachen och gäller alla inlägg som refererar samma bild.

### Välja befintlig bild

Om bilden redan finns i cachen visas **miniatyrer** under uppladdningsfältet. Klicka på en miniatyr för att välja bild och ladda caption. Vald bild markeras med ram.

## Steg — endast text

1. Välj **+ Ny i verkstaden** (eller **Redigera** på ett befintligt budskap).
2. Vid nytt budskap: välj typ **Post** eller **Nyhet**.
3. Låt innehållsläge stå på **Endast text**.
4. Skriv **brödtexten**.
5. Om du har en **käll-URL**: klistra in den och välj **Hämta & sammanfatta**.
6. Ange **titel** (föreslås från brödtexten om du lämnar den tom).
7. Välj **Generera varianter…** om du vill ha tre formuleringar (Analytisk, Berättande, Koncis).
8. **Spara till biblioteket**.

## Steg — endast bild eller bild + text

1. Välj typ **Post** eller **Nyhet** och innehållsläge **Endast bild** eller **Bild + text**.
2. **Ladda upp** en bild (JPEG, PNG, WebP eller GIF) — eller **välj miniatyr** från cachade bilder.
3. Granska och **justera caption** om du vill. Caption är obligatorisk och blir det agenterna ser av bildinnehållet.
4. Vid **Bild + text**: skriv valfri **följtext** under bildblocket.
5. Ange **titel** (föreslås från caption eller följtext).
6. **Spara till biblioteket**.

Variantgenerering (**Generera varianter…**) är tillgänglig för textläge, inte för rena bildbudskap.

## Relaterade guider

- [Hantera budskap](hantera-budskap.md)
- [Hantera cache](hantera-embedding-cache.md) — ta bort enskilda cachade bilder
- [Konfigurera en dag i tidslinjen](konfigurera-dag-i-tidslinjen.md)
