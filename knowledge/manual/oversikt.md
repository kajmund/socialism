---
type: guide
title: Översikt av ytorna
description: Var du hittar adminytorna i Socialism.
tags: [korningar, personas, populationer, budskap, grunddata, jobb, rapporter]
---

# Översikt av ytorna

Socialism är en adminyta (mörk Devbrains-stil) för det dagliga arbetet med personas, populationer och körningar. Du måste [logga in](logga-in.md) innan du kommer in.

## Startsida (dashboard)

När du öppnar appen och är inloggad landar du på **dashboard** (`/`). Där ser du snabbstart, senaste körningar, aktiva bakgrundsjobb, biblioteksstatistik och senaste rapporter. Om inget är skapat ännu visas en **Kom igång**-guide med steg i rätt ordning.

## Admin (det du använder till vardags)

Huvudmenyn ligger som en **vertikal list till vänster**. Vilka länkar som syns styrs av vilka **moduler** kunden har påslagna. Administratör ser vissa ytor även utan att varje modulruta är ikryssad; i **bolagsytan** (`/bolag`) visas bara bolagets egna moduler. Från menyn når du bland annat:

### Gemensamt (nästan alltid)

1. **Rapporter** — beställda rapporter, med flikar per modul när flera rapportmoduler är på. Se [Hantera rapporter](hantera-rapporter.md).
2. **Återkoppling** — buggar, idéer och åsikter sparade från hjälpchatten
3. **Jobb** — bakgrundsjobb (generering, simulering, rapporter)

### Efter modul

- **Politik** — Körningar, Personas, Populationer, Budskap
- **Due Diligence** — Kampanjer (i bolagsytan när kontot är DD-only)
- **Expertgranskning** — Expertgranskning; **Experter** och **Expertpaneler** ligger under rubriken **Experter** precis ovanför Rapporter/Återkoppling/Jobb
- **Rättsunderlag** — Rättsunderlagssökning
- **Tabular Review** — jämförelse av avtal mot klausulankare (`/tabular-review`) när modulen är på

### Administratör och profil

- **Verktyg** — konfigurationer, kunder, panelkatalog, SSR-ankare, playground, cache, expertminnen och LLM. Se [Använda Verktyg (administratör)](anvanda-verktyg.md).
- **Användare** — administrera konton (`/anvandare`), syns för administratör
- **Profil** — ditt eget konto via länken i sidhuvudet (`/profil`), inte i sidomenyn

På en liten skärm öppnar du menyn med knappen uppe till höger.

En execution-körning (annan sak än simulering) öppnas via direktlänk; se [Inspektera en execution-körning](inspektera-execution-run.md).

## Relaterade guider

- [Logga in](logga-in.md)
- [Hantera körningar](hantera-korningar.md)
- [Skapa en ny körning](skapa-korning.md)
- [Starta en simulering](starta-simulering.md)
- [Använda hjälpchatten](anvanda-hjalpchatten.md)
- [Använda Verktyg (administratör)](anvanda-verktyg.md)
- [Använda playground](anvanda-playground.md)
- [Hantera embedding-cache](hantera-embedding-cache.md)
- [Visa expertminnen](visa-expertminnen.md)
- [Öppna rapporter per modul](oppna-rapporter-per-modul.md)
- [Tabular Review](tabular-review.md)
