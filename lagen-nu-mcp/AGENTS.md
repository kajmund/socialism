# lagen-nu-mcp

MCP-server + cache-pipeline för lagen.nu. Eget repo, inte del av socialism-monorepot.

## Stack

- Python 3.12+
- Supabase Postgres, schema `lagen_nu`
- stdlib HTTP (`urllib`) + `psycopg`
- LLM-prompts hör inte hemma här

## Regler

- En settingsmodul: `lagen_nu_mcp/config.py`. Ingen `os.getenv` i övrig appkod.
- Inga tysta fallbacks. JSON-hämtning i Fas 2 får falla till HTML/XHTML för att content-negotiation är specifikationen (lagen.nu svarar idag med HTML oavsett Accept).
- MCP-verktyg läser bara cachen. Aldrig live mot lagen.nu per query.
- Rate limit mot lagen.nu: max ~1 req/s, identifierande User-Agent.
- Håll pollern artig. Default är de 6 kategorifeederna, inte alla filter-URL:er på sitenews.
- Fas 6 (pgvector / Vector Buckets) är avvaktande. Bygg inte embeddings förrän Fas 3-`tsvector` visat sig otillräcklig.

## Layout

```text
sql/001_schema.sql          # lagen_nu.*
src/lagen_nu_mcp/           # poller (Fas 1), fetcher (Fas 2), senare MCP
tests/
```
