---
type: guide
title: Hantera cache
description: Så visar och rensar du cachade SSR-ankarembeddings och budskapsbilder.
tags: [grunddata, budskap]
---

# Hantera cache

Under **Verktyg** → **Cache** finns två typer av cache: **SSR-embeddings** (ankare för rapporter och playground) och **budskapsbilder** (uppladdade bilder med vision-caption).

## SSR-embedding-cache

SSR sparar embeddings för ankarpåståenden på disk så samma ankare inte behöver beräknas om vid varje rapport eller playground-körning.

1. Öppna **Verktyg** → **Cache**.
2. Den övre listan visar cachad **text**, **modell**, antal **dimensioner** och när posten uppdaterades.
3. **Uppdatera** hämtar listan på nytt.
4. **Rensa cache** tar bort alla embedding-poster (minne och disk). Nästa SSR-körning beräknar ankare på nytt.

Rensa embedding-cachen om du bytt embedding-modell eller misstänker gamla vektorer efter att ankarteexterna ändrats.

## Bild-cache (budskap)

Varje bild som laddats upp i **budskapsverkstaden** sparas med **SHA256-nyckel** och en **caption** från vision-modellen. Samma fil ger cache träff utan ny caption-generering.

1. Scrolla till avsnittet **Bild-cache** på samma sida.
2. Varje rad visar **miniatyr**, **caption**, kort **SHA256** och **senast uppdaterad**.
3. **Ta bort** på en rad raderar just den bilden (bytes + caption) från cachen.

**Obs:** Budskap i biblioteket som refererar en borttagen hash kan inte startas i simulering förrän du laddar upp bilden igen eller byter bild på budskapet.

Caption redigeras i **verkstaden**, inte på cachesidan — ändringar där gäller alla inlägg som delar samma bild.

## Relaterade guider

- [Skapa budskap i verkstaden](skapa-budskap-i-verkstaden.md)
- [Använda playground](anvanda-playground.md)
- [Hantera konfigurationer](hantera-konfigurationer.md)
