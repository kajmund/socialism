---
type: guide
title: Hantera konfigurationer
description: Så skapar, redigerar och aktiverar du konfigurationer med prompttexter och grunddata.
tags: [grunddata]
---

# Hantera konfigurationer

Ytan **Verktyg** → **Konfigurationer** syns bara för **administratör**. Inloggade som **användare** når den inte från menyn.

I **Konfigurationer** sparar du **prompttexter** (persona, chat, budskap, OASIS och rapport), **SSR-temperatur** och **rapporttrösklar** för snabbrapportens slutsats och rekommendation, samt **grunddata** (kataloglistor) och **ankare**. Prompttexterna gäller **direkt** för kunden och språket — du behöver inte aktivera för att en promptändring ska användas. Endast **en** konfiguration kan vara aktiv åt gången; **Aktivera** styr SSR, ankare och grunddata, inte LLM-promptarna. Det är oberoende av språkvalet i menyn.

## Steg

1. Öppna **Verktyg** → **Konfigurationer** i menyn.
2. I listan syns **namn**, **promptspråk** och om posten är **Aktiv**. Växla mellan **Rutnät** och **Lista** vid behov.
3. Skapa nytt med **+ Ny konfiguration** — promptfälten fylls i med standardtexter.
4. I sidhuvudet: ge konfigurationen ett **Namn**, välj **promptspråk** (SV/EN/NB) och slå på **Aktiv** om den här postens SSR, ankare och grunddata ska användas. **Spara** och **Avbryt** sitter till höger i samma rad.
5. Under fliken **Innehåll & ton**: sök eller bläddra i listan till vänster och redigera **ett promptfält i taget**. Du kan återställa ett fält till standardtexten.
6. Under fliken **Känslighet & rapportgränser**: välj en grupp i vänstermenyn. **Variation i svar** är SSR-temperatur (lägre = skarpare ton/stil-fördelning; kalibrera gärna i Playground först). Övriga grupper är rapporttrösklar (hur slutsats och rekommendation tolkas). Standardvärden räcker oftast — ändringar gäller bara **nya** rapporter. Under **Avancerat** finns poängformel och **målgruppssammanfattning**.
7. Under fliken **Ankare**: välj publicerat **ton-** och **stilankare** för svenska respektive engelska rapporter.
8. **Spara** — du landar i redigeringsläget där fliken **Grunddata** blir tillgänglig.
9. Under **Grunddata** redigerar du kataloglistor för just den här konfigurationen.
10. Du kan också aktivera senare från listan. När du aktiverar en post blir övriga inaktiva. Prompttexterna påverkas inte av aktiveringen.
11. På ett kort: **Redigera**, **Aktivera** (om den inte redan är aktiv) eller **Ta bort**.

## Relaterade guider

- [Använda playground](anvanda-playground.md)
- [Redigera grunddata](redigera-grunddata.md)
- [Hantera SSR-ankare](hantera-ssr-ankare.md)
- [Översikt av ytorna](oversikt.md)
