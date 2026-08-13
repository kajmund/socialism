---
type: guide
title: Hantera konfigurationer
description: Så skapar, redigerar och aktiverar du konfigurationer med prompts och grunddata.
tags: [grunddata]
---

# Hantera konfigurationer

I **Konfigurationer** sparar du kompletta uppsättningar av **prompttexter** (persona, chat, budskap, OASIS och rapport), **SSR-temperatur** och **rapporttrösklar** för snabbrapportens slutsats och rekommendation, samt **grunddata** (kataloglistor). Endast **en** konfiguration kan vara aktiv åt gången — den är den backend använder för både LLM-texter, SSR i rapporter och dropdowns. Det är oberoende av språkvalet i menyn.

## Steg

1. Öppna **Verktyg** → **Konfigurationer** i menyn.
2. I listan syns **namn**, **promptspråk** och om posten är **Aktiv**.
3. Skapa nytt med **+ Ny konfiguration** — promptfälten fylls i med standardtexter.
4. Ge konfigurationen ett **Namn**, välj **Promptspråk** och redigera under fliken **Promptinställningar** (t.ex. Persona, Chat & intervju).
5. Under fliken **SSR-ankare**: **SSR-temperatur** (lägre = skarpare ton/stil-fördelning; kalibrera gärna i Playground först), val av ton-/stilankare, och **Rapporttrösklar** (hur slutsats och rekommendation tolkas). Standardtrösklar räcker oftast — ändringar gäller bara **nya** rapporter; befintliga behåller trösklarna från när de genererades. Under **Avancerat** finns även trösklar för **målgruppssammanfattning** (korta takeaway-stycken) — separata från rekommendationens narrativa triggare.
6. **Spara** — du landar i redigeringsläget där fliken **Grunddata** blir tillgänglig.
7. Under **Grunddata** redigerar du kataloglistor för just den här konfigurationen.
8. Markera **Aktiv** om den ska användas direkt, eller aktivera senare från listan. När du aktiverar en post blir övriga inaktiva.
9. På ett kort: **Redigera**, **Aktivera** (om den inte redan är aktiv) eller **Ta bort**.

## Relaterade guider

- [Använda playground](anvanda-playground.md)
- [Redigera grunddata](redigera-grunddata.md)
- [Översikt av ytorna](oversikt.md)
