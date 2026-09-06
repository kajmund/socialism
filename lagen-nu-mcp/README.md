# lagen-nu-mcp

> Tillfälligt parkerad i `socialism` tills Cursor har write på det egna repot [`kajmund/lagen-nu-mcp`](https://github.com/kajmund/lagen-nu-mcp). Inte en del av Socialism-appen. Flytta ut och ta bort den här katalogen när det repot är igång.

MCP-server och cache-pipeline för svensk lagtext, rättsfall och förarbeten från [lagen.nu](https://lagen.nu).

Data hämtas från lagen.nus publika Atom-feeds, cachas i Supabase Postgres (schema `lagen_nu`) och läses **bara** från cachen av MCP-verktygen. Ingen live-skrapning per query.

Skrapning av lagen.nu är juridiskt/avtalsmässigt godkänd. Tjänsten är ideell och volontärdriven — vi håller en identifierande `User-Agent` och max ~1 req/s.

## Status

| Fas | Innehåll | Läge |
| --- | --- | --- |
| 1 | Feed-poller → `pending_fetch` | **v1, den här koden** |
| 2 | Fetcher + schema (dokument + SFS-versioner) | **v1.** `python -m lagen_nu_mcp fetch` |
| 3 | Svensk `tsvector`-sökning, gärna per paragraf | Kolumn + GIN i schemat. Paragrafindex fylls av fetchern. |
| 4 | MCP-verktyg (search/get SFS, rättsfall, förarbeten) | Inte påbörjad |
| 5 | Paragraf-diff mellan `document_versions` | Efter MVP |
| 6 | Semantisk sökning (`pgvector`) | Avvaktande — se nedan |

## Fas 1 — poller

Cron (t.ex. varje timme):

1. Hämtar kategorifeeds (`sfs`, `dv`, `forarbeten`, `myndfs`, `myndprax`, `keyword`).
2. Parsar varje entry: `<id>` + `<updated>`.
3. Jämför mot `lagen_nu.feed_state.last_seen_entry_updated`.
4. Skriver nya/ändrade dokument-URL:er till `lagen_nu.pending_fetch` (upsert på URL).
5. Loggar `new` / `seen` per feed.

Första körningen enqueuar allt på den *aktuella* feedsidan (lagen.nu paginerar äldre poster via `prev-archive` på äldre Ferenda-feeds). Arkiv-backfill är inte med i Fas 1.

### Varför 6 feeds, inte ~66?

[sitenews](https://lagen.nu/dataset/sitenews) listar många Atom-URL:er. Flera är filter på samma dataset plus en överordnad “alla”-feed. Default `LAGEN_NU_FEED_MODE=roots` pollar de sex dataset-feederna. `all` upptäcker varje `feed.atom` på sitenews (utom sitenews själv).

## Schema

Eget schema `lagen_nu` i samma Supabase-projekt som Socialism. Poller/fetcher kör med service-role. RLS avstängt i v1.

`pending_fetch` fanns i Fas 1-beskrivningen men inte i Fas 2-DDL:n — den är tillagd i `sql/001_schema.sql`.

```bash
psql "$DATABASE_URL" -f sql/001_schema.sql
```

## Köra pollern

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env   # fyll i DATABASE_URL

python -m lagen_nu_mcp poll
python -m lagen_nu_mcp poll --store memory
python -m lagen_nu_mcp fetch --limit 20
```

Fetchern tömmer `pending_fetch`, hämtar varje URL med `Accept: application/json` först (lagen.nu svarar idag med HTML) och sparar body + paragrafer. För SFS roteras `document_versions` när `Ändring införd t.o.m.` ändrats; den gamla raden får `konsolidering_url`.

Cron-exempel:

```cron
12 * * * * cd /opt/lagen-nu-mcp && .venv/bin/python -m lagen_nu_mcp poll
```

### Identitet mot lagen.nu

```
User-Agent: lagen-nu-mcp/0.1 (+https://github.com/kajmund/lagen-nu-mcp; erik@devbrains.se)
LAGEN_NU_MIN_INTERVAL_SECONDS=1.0
```

## Tester

```bash
pip install -e '.[dev]'
pytest
```

## Kända begränsningar (ej blockerande)

- Helt upphävda lagar försvinner från lagen.nu. Historik finns bara för det vi själva hann arkivera.
- Community-kommentarer (CC-BY-SA) saknar feed-signal. Utelämnas i v1.
- Endast vägledande rättsfall (inte tings-/förvaltningsrätt). Kompletterande källa vid behov: Domstolsverket / offentligmcp.se.
- MCP-verktygen (Fas 4) läser enbart cachen, aldrig live mot lagen.nu.

## Fas 4-verktyg (plan)

- `search_law(query)` — fritext mot `search_vector`, SFS-nr + paragraf
- `get_sfs(sfs_nr, paragraf?)` — aktuell lagtext, ankare `P9` / `P26a`
- `get_law_history(sfs_nr)` — ändringspunkter ur `document_versions`
- `get_law_version(sfs_nr, amending_sfs)` — historisk lydelse
- `search_case_law(query)` / `get_case(ref, domstol)` — AD/HFD/MD/MIÖD/MÖD/NJA/PMÖD/RÅ/RH/RK
- `get_forarbete(id)` — prop/SOU/Ds/dir
- `diff_law_versions(sfs_nr, from_sfs, to_sfs)` — Fas 5, efter MVP

## Fas 6 — semantisk sökning (avvaktande, ej blockerande)

Bygg **inte** detta nu.

- `pgvector` i samma Supabase-projekt är kandidaten för embeddingbaserad paragrafsökning, men bara om/när Fas 3-`tsvector` inte räcker.
- Supabase Vector Buckets (S3, public alpha) utvärderas först *efter* att funktionen lämnat alpha.
