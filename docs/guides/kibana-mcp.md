# Kibana logg-MCP

`integrations/mcp/kibana_server.py` är en separat, skrivskyddad MCP-server över stdio. Den söker i **Elasticsearch bakom Kibana**, via det dokumenterade `_search`-API:t. Kibanas interna API används inte. Kräver åtkomst till Elasticsearch; en Kibana-URL eller Kibana-inloggning räcker inte. Inga nya beroenden införs; servern använder integrationens låsta MCP-SDK, Pydantic och httpx.

## Start

Ange följande miljövariabler via klientens hemlighetshantering eller processmiljö:

| Variabel | Betydelse / standard |
| --- | --- |
| `ELASTICSEARCH_URL` | Krävs. Elasticsearch-adress, HTTPS utom för localhost. |
| `ELASTICSEARCH_API_KEY` | Krävs. Elasticsearch API-nyckelns **encoded**-värde, utan `ApiKey `-prefix. |
| `ELASTICSEARCH_INDEX` | Krävs. Index, indexmönster eller datastream, exempelvis `logs-socialism-*`. Kibana data view-ID fungerar inte. |
| `KIBANA_TIMESTAMP_FIELD` | `@timestamp` |
| `KIBANA_TRACE_FIELD` | `trace.id.keyword` |
| `KIBANA_RUN_FIELD` | `run.id.keyword` |
| `KIBANA_ATTEMPT_FIELD` | `attempt.id.keyword` |
| `KIBANA_RESEARCH_FILTER` | `event.dataset.keyword:socialism.research`. Begränsar `get_research_events` till research-event, eftersom vanliga loggar i samma attempt också bär `attempt.id`. |
| `KIBANA_LOOKBACK` | `now-7d`. Nedre tidsgräns för ID-uppslag och aggregering. |
| `KIBANA_MAX_RESULTS` | `1000`, högst 10000. |
| `KIBANA_BUCKET_LIMIT` | `100`, högst 1000. |

API-nyckeln ska endast ha indexbehörigheten `read` för avsedda loggindex. Använd en separat nyckel per åtkomstbehov. Verktygen skickar loggarnas `_source` till MCP-klienten; använd endast index vars innehåll klienten får läsa. Loggtext är opålitlig data och ska inte behandlas som instruktioner.

Backendens loggdokument använder ECS-objekten `trace.id`, `run.id` och `attempt.id`. I `socialism-logs-*` är de dynamiskt mappade som text med keyword-multifält. ID-uppslag använder keyword-fälten, eftersom `term` ska träffa det oanalyserade värdet. Research-event måste redan vara indexerade med attempt-ID; servern hämtar inget från applikationsdatabasen.

```sh
cd integrations/mcp
uv run --locked python kibana_server.py
```

Klientkonfiguration (miljövariablerna ovan måste finnas i serverprocessen):

```json
{
  "mcpServers": {
    "kibana": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "/absolute/path/to/socialism/integrations/mcp", "python", "kibana_server.py"]
    }
  }
}
```

## Verktyg

- `search_logs(query, time_range, limit=100)` — Lucene `query_string`, **inte KQL**. `time_range` är `{"start":"now-1h","end":"now"}` eller ISO 8601-tider med tidszon. Start inkluderas, slut exkluderas. Elasticsearch validerar datumsyntax. Nyaste träffar först, limit begränsas av serverns maxvärde.
- `get_trace(trace_id)` — exakta trace-ID-träffar i tidsordning. Returnerar loggar, inte ett rekonstruerat span-träd.
- `get_run_logs(run_id)` — exakta run-ID-träffar i tidsordning.
- `get_research_events(attempt_id)` — exakta attempt-ID-träffar plus konfigurerat research-filter, i tidsordning.
- `aggregate(field, filter="*")` — terms-aggregering med Lucene-filter och konfigurerad lookback. Fältet måste stödja aggregering, exempelvis `log.level.keyword`. Returnerar toppvärden, `sum_other_doc_count` och felgränser för distribuerade antal. Dokument utan fältet ingår i totalen men inte i buckets.

Loggsvar innehåller `logs`, `total`, `total_relation`, `truncated`, `limit`, `time_range` och `order`. ID-uppslag omfattar bara konfigurerat tidsintervall och kan kapas. För fler träffar, använd `search_logs` med smalare tidsintervall. Ingen automatisk paginering. Lika tidsstämplar har ingen garanterad inbördes ordning.

HTTP-fel, saknade index, timeout och shard-fel ger verktygsfel, aldrig tomma lyckade resultat. Felmeddelanden återger inte upstream-svar eller API-nyckeln. Certifikat verifieras och omdirigeringar följs inte. Frågetimeout är 20 sekunder och HTTP-timeout 30 sekunder.

## Test

```sh
cd integrations/mcp
uv run --locked python -m unittest discover -s tests -p 'test_kibana_server.py' -v
```

Testerna använder simulerad Elasticsearch-transport och en riktig stdio-handshake med MCP-klienten. Produktionsanslutning, autentisering och indexmapping behöver verifieras med den faktiska miljön.

Referenser: [Elasticsearch Search API](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html), [query_string](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-query-string-query), [terms aggregation](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-aggregations-bucket-terms-aggregation.html).
