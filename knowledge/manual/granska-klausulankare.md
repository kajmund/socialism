---
type: guide
title: Granska klausulankare
description: Svara Ja eller Nej på en klausul i taget så att biblioteket får verifierade exempel.
tags: [grunddata]
---

# Granska klausulankare

**Klausulankare** är en administratörskö där du klassificerar klausuler med Ja eller Nej. Svaren sparas. Ett Ja betyder bara att klausulen matchar den ställda frågan — det blir inte automatiskt ett aktivt ankare.

## Öppna kön

1. Logga in som **administratör**.
2. Öppna **Verktyg** → **Klausulankare**.
3. Välj frågan, till exempel *Är det här en uppsägningsklausul?*.
4. Filtrera på dokument-id om du bara vill granska ett avtal.

## Skapa en ny fråga

Behöver du en ny ja/nej-fråga för en klausultyp som inte finns i listan:

1. Fyll i **slug** (kort tekniskt namn, utan mellanslag), **kategori** (t.ex. uppsägning) och själva **frågan** i fälten ovanför kön.
2. Klicka **Skapa fråga**. Frågan läggs till i listan och väljs automatiskt.
3. Granska klausuler som vanligt. Svaren knyts till den nya frågan.

## Svara

Varje kort visar en klausul, frågan, kategori, källa och eventuellt en **SSR-likhet**. Likheten är cosine-similarity, inte en sannolikhet.

- **Ja** — klausulen hör till frågan.
- **Nej** — klausulen hör inte till *den här* frågan. Den kan fortfarande höra till en annan fråga.
- **Hoppa över** eller **Osäker** — inget etikett. De räknas inte som nej.

Tangentbord: **J** ja, **N** nej, **S** hoppa över, **U** osäker, **P** föregående, **Z** ångra.

Nästa kort kommer utan omladdning. Om sparandet misslyckas stannar kortet kvar.

## Återuppta och ångra

Kön kommer ihåg dina svar. Öppna samma fråga igen för att fortsätta. **Ångra** tar bort det senaste svaret.

## Relaterade guider

- [Använda Verktyg (administratör)](anvanda-verktyg.md)
- [Hantera SSR-ankare](hantera-ssr-ankare.md)
