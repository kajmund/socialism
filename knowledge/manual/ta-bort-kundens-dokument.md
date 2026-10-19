---
type: guide
title: Rensa en kunds dokument
description: Så raderar du en kunds uppladdade dokument och den kunskap som byggts från dem under Verktyg → Kunder.
tags: [grunddata]
---

# Rensa en kunds dokument

**Rensa dokument** tar permanent bort en kunds uppladdade dokument och den kunskap som byggts från dem. **Borttagningen kan inte ångras.**

Ytan syns bara för **administratör** under **Verktyg** → **Kunder**.

## Vad som raderas

- Kundens uppladdade underlag och dokument i alla moduler och workspaces.
- Kunskapen som byggts från dokumenten:
  - dokumentindex och dokumentförståelse
  - kanoniska dokumentposter
  - textenheter
  - påståenden, entiteter och relationer
  - kunskapsgrafen
  - vektorembeddings
  - inläsningsomgångar (batcher)

## Vad som inte raderas

- Användarkonton.
- Personas.
- Körningar.
- Rapporter.
- Experternas långtidsminnen.
- Delad eller global kunskap.
- Kundens övriga data.

## Steg

1. Öppna **Verktyg** → **Kunder**.
2. Hitta raden för kunden.
3. Välj **Rensa dokument**.
4. Granska antalen som visas — de visar hur mycket som tas bort.
5. Skriv kundens **slug** i fältet för att bekräfta.
6. Välj den **destruktiva bekräftelseknappen**.

**Borttagningen kan inte ångras.** Dokumenten och kunskapen som byggts från dem går inte att återställa.

## Om borttagningen blockeras

Om borttagningen blockeras för att ett jobb med dokument-ingest eller graf-ingest pågår för kunden, vänta tills jobbet är klart eller stoppa det och försök igen.

## Relaterade guider

- [Hantera kundmoduler](hantera-kundmoduler.md)
- [Redigera kundens organisationsuppgifter](redigera-kundens-organisationsuppgifter.md)
- [Använda Verktyg (administratör)](anvanda-verktyg.md)
