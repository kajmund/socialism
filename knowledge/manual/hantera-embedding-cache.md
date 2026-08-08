---
type: guide
title: Hantera embedding-cache
description: Så visar och rensar du cachade SSR-ankarembeddings.
tags: [grunddata]
---

# Hantera embedding-cache

SSR sparar embeddings för ankarpåståenden på disk så samma ankare inte behöver beräknas om vid varje rapport eller playground-körning.

## Steg

1. Öppna **Verktyg** → **Cache**.
2. Listan visar cachad **text**, **modell**, antal **dimensioner** och när posten uppdaterades.
3. **Uppdatera** hämtar listan på nytt.
4. **Rensa cache** tar bort alla poster (minne och disk). Nästa SSR-körning beräknar ankare på nytt.

Rensa om du bytt embedding-modell eller misstänker gamla vektorer efter att ankarteexterna ändrats i kod/defaults.

## Relaterade guider

- [Använda playground](anvanda-playground.md)
- [Hantera konfigurationer](hantera-konfigurationer.md)
