import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from dataclasses import replace
from mcp.server.mcpserver.exceptions import ToolError

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kibana_server import LogReader, Settings, TimeRange, create_server


class KibanaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings("https://elastic.example", "test-secret", "logs-*", max_results=2)
        self.requests = []

        def respond(request):
            self.requests.append(request)
            return httpx.Response(200, json={
                "timed_out": False, "_shards": {"failed": 0},
                "hits": {"total": {"value": 3, "relation": "eq"}, "hits": [
                    {"_id": "1", "_index": "logs-1", "_source": {"message": "first"}},
                    {"_id": "2", "_index": "logs-1", "_source": {"message": "second"}},
                ]},
                "aggregations": {"values": {"buckets": [{"key": "error", "doc_count": 2}], "sum_other_doc_count": 1, "doc_count_error_upper_bound": 0}},
            })

        self.transport = httpx.MockTransport(respond)
        self.server = create_server(self.settings, self.transport)

    async def invoke(self, name, arguments):
        result = await self.server.call_tool(name, arguments)
        self.assertFalse(result.is_error)
        return json.loads(result.content[0].text)

    async def test_registration_and_search(self):
        tools = await self.server.list_tools()
        self.assertEqual({tool.name for tool in tools}, {"search_logs", "get_trace", "get_run_logs", "get_research_events", "aggregate"})
        self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))
        result = await self.invoke("search_logs", {"query": "level:ERROR", "time_range": {"start": "now-1h"}, "limit": 100})
        self.assertTrue(result["truncated"])
        self.assertEqual(result["limit"], 2)
        request = self.requests[-1]
        body = json.loads(request.content)
        self.assertEqual(request.url.path, "/logs-*/_search")
        self.assertEqual(request.headers["Authorization"], "ApiKey test-secret")
        self.assertEqual(body["query"]["bool"]["filter"][0], {"range": {"@timestamp": {"gte": "now-1h", "lt": "now"}}})
        self.assertEqual(body["sort"], [{"@timestamp": "desc"}])
        self.assertEqual(request.url.params["allow_partial_search_results"], "false")

    async def test_identifiers_are_not_query_syntax(self):
        for name, key, field in [("get_trace", "trace_id", "trace.id.keyword"), ("get_run_logs", "run_id", "run.id.keyword"), ("get_research_events", "attempt_id", "attempt.id.keyword")]:
            with self.subTest(name=name):
                identifier = 'x" OR *:*'
                result = await self.invoke(name, {key: identifier})
                body = json.loads(self.requests[-1].content)
                self.assertIn({"term": {field: identifier}}, body["query"]["bool"]["filter"])
                if name == "get_research_events":
                    self.assertIn(
                        {"query_string": {"query": "event.dataset.keyword:socialism.research"}},
                        body["query"]["bool"]["filter"],
                    )
                self.assertEqual(result["time_range"]["start"], "now-7d")
                self.assertEqual(body["sort"], [{"@timestamp": "asc"}])

    async def test_aggregation_reports_omitted_counts(self):
        result = await self.invoke("aggregate", {"field": "level.keyword", "filter": "service.name:backend"})
        self.assertEqual(result["sum_other_doc_count"], 1)
        self.assertEqual(result["doc_count_error_upper_bound"], 0)
        body = json.loads(self.requests[-1].content)
        self.assertEqual(body["size"], 0)
        self.assertEqual(body["aggs"]["values"]["terms"]["field"], "level.keyword")

    async def test_input_validation_precedes_http(self):
        for name, args in [("search_logs", {"query": "*", "time_range": {"start": "now-1h"}, "limit": 0}), ("get_trace", {"trace_id": ""}), ("aggregate", {"field": "foo/script"})]:
            with self.subTest(name=name), self.assertRaises(ToolError):
                await self.invoke(name, args)
        self.assertEqual(self.requests, [])

    async def test_upstream_failures_are_not_empty_success(self):
        responses = [httpx.Response(302, headers={"Location": "https://other.example"}), httpx.Response(401, text="test-secret"), httpx.Response(200, json={"timed_out": True}), httpx.Response(200, json={"_shards": {"failed": 1}}), httpx.Response(200, text="invalid")]
        for response in responses:
            reader = LogReader(self.settings, httpx.MockTransport(lambda request: response))
            with self.subTest(response=response), self.assertRaises(ValueError) as caught:
                await reader.logs([], 1)
            self.assertNotIn("test-secret", str(caught.exception))

    async def test_empty_results(self):
        reader = LogReader(self.settings, httpx.MockTransport(lambda request: httpx.Response(200, json={"hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}})))
        result = await reader.logs([], 1)
        self.assertEqual(result["logs"], [])
        self.assertFalse(result["truncated"])

    async def test_custom_mapping_and_research_filter(self):
        settings = replace(self.settings, attempt_field="research.attempt_id", research_filter="event.kind:research", lookback="now-30d")
        self.server = create_server(settings, self.transport)
        await self.invoke("get_research_events", {"attempt_id": "attempt-1"})
        filters = json.loads(self.requests[-1].content)["query"]["bool"]["filter"]
        self.assertIn({"term": {"research.attempt_id": "attempt-1"}}, filters)
        self.assertIn({"query_string": {"query": "event.kind:research"}}, filters)
        self.assertEqual(filters[0]["range"]["@timestamp"]["gte"], "now-30d")

    async def test_connection_timeout(self):
        def timeout(request):
            raise httpx.ReadTimeout("secret upstream detail", request=request)
        reader = LogReader(self.settings, httpx.MockTransport(timeout))
        with self.assertRaisesRegex(ValueError, "connection failed or timed out"):
            await reader.logs([], 1)

    def test_config_fails_fast(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            Settings.from_env()
        for url in ["http://remote.example", "https://user:password@remote.example", "file:///tmp/logs"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                Settings(url, "key", "logs-*")

    async def test_real_stdio_handshake(self):
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve().parents[1] / "kibana_server.py")], env={
            "ELASTICSEARCH_URL": self.settings.url,
            "ELASTICSEARCH_API_KEY": self.settings.api_key,
            "ELASTICSEARCH_INDEX": self.settings.index,
        })
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                self.assertEqual(len(result.tools), 5)


if __name__ == "__main__":
    unittest.main()
