"""Read-only analysis tools over RunBundles + metrics (for LLM agent)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.services.report.bundles import RunBundle, is_ab_comparison
from app.services.report.metrics import ReportMetrics, compute_report_metrics, pct

ToolHandler = Callable[..., Any]


class ReportToolBundle:
    def __init__(self, bundles: list[RunBundle], metrics: ReportMetrics | None = None) -> None:
        self.bundles = bundles
        self.metrics = metrics or compute_report_metrics(bundles)

    def describe_runs(self) -> dict[str, Any]:
        ab = is_ab_comparison(self.bundles)
        return {
            "n_runs": self.metrics.n_runs,
            "comparison_mode": "ab_test" if ab else ("multi_run" if self.metrics.n_runs > 1 else "single"),
            "tone_mode": self.metrics.tone_mode,
            "runs": [
                {
                    "label": b.label,
                    "run_id": b.run_id,
                    "attempt_id": b.attempt_id,
                    "variant_id": b.variant_id,
                    "agents": self.metrics.bundles[i].agent_count
                    if i < len(self.metrics.bundles)
                    else len(b.agents),
                    "posts": len(b.posts),
                    "comments": len(b.comments),
                    "ticks_run": b.ticks_run,
                    "personas": len(b.personas),
                    "seed": b.seed,
                    "injection_count": len(b.injection_texts),
                }
                for i, b in enumerate(self.bundles)
            ],
            "aggregate": {
                "gini": self.metrics.aggregate.gini,
                "zero_like_agents": self.metrics.aggregate.zero_like_agents,
                "agent_count": self.metrics.aggregate.agent_count,
                "topic_shares": {
                    k: pct(v) for k, v in self.metrics.aggregate.topic_shares.items()
                },
                "tone_shares": {
                    k: pct(v) for k, v in self.metrics.aggregate.tone_shares.items()
                },
                "style_avg_likes": [
                    {"style": s, "avg_likes": a}
                    for s, a in self.metrics.aggregate.style_avg_likes
                ],
            },
            "notes": (
                (
                    "A/B-test: varje 'run' i listan är en arm (Version A / Version B). "
                    "Jämför dem — slå inte ihop till en debatt. "
                )
                if ab
                else ""
            )
            + (
                "Ämnesandelar bygger på LLM-ämnespack från injektioner; "
                "ton och stil är SSR (embeddings av reaktionstexter mot ankare). "
                "Använd endast dessa procenttal — hitta inte på Äldreomsorg/Trafik om de saknas."
            ),
        }

    def compare_engagement(self) -> dict[str, Any]:
        return {
            "per_run": [
                {
                    "label": m.label,
                    "gini": m.gini,
                    "top": m.top_agents,
                    "mid": m.mid_agents,
                    "zero": m.zero_like_agents,
                    "agents": m.agent_count,
                }
                for m in self.metrics.bundles
            ]
        }

    def compare_topics(self) -> dict[str, Any]:
        return {
            "per_run": [
                {"label": m.label, "shares": {k: pct(v) for k, v in m.topic_shares.items()}}
                for m in self.metrics.bundles
            ]
        }

    def compare_tone(self) -> dict[str, Any]:
        return {
            "per_run": [
                {"label": m.label, "shares": {k: pct(v) for k, v in m.tone_shares.items()}}
                for m in self.metrics.bundles
            ]
        }

    def opinion_leaders(self, limit: int = 5) -> dict[str, Any]:
        return {
            "per_run": [
                {"label": m.label, "actors": m.top_actors[:limit]}
                for m in self.metrics.bundles
            ]
        }

    def sample_comments(self, *, limit: int = 20, query: str | None = None) -> dict[str, Any]:
        out: dict[str, list[dict[str, Any]]] = {}
        q = (query or "").lower().strip()
        for b in self.bundles:
            rows: list[dict[str, Any]] = []
            for c in b.comments:
                text = str(c.get("content") or c.get("text") or "")
                if q and q not in text.lower():
                    continue
                rows.append(
                    {
                        "user_id": c.get("user_id") or c.get("agent_id"),
                        "content": text[:400],
                        "likes": c.get("num_likes") or c.get("likes") or 0,
                    }
                )
                if len(rows) >= limit:
                    break
            out[b.label] = rows
        return out

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "describe_runs": lambda: self.describe_runs(),
            "compare_engagement": lambda: self.compare_engagement(),
            "compare_topics": lambda: self.compare_topics(),
            "compare_tone": lambda: self.compare_tone(),
            "opinion_leaders": lambda limit=5: self.opinion_leaders(int(limit)),
            "sample_comments": lambda limit=20, query=None: self.sample_comments(
                limit=int(limit), query=query
            ),
        }

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "describe_runs",
                    "description": "Metadata, volymer och aggregat per körning.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_engagement",
                    "description": "Gini och likes-fördelning per körning.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_topics",
                    "description": "Ämnesandelar per körning.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_tone",
                    "description": "Tonproxies per körning.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "opinion_leaders",
                    "description": "Toppagenter efter likes.",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sample_comments",
                    "description": "Stickprov av kommentars text.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer"},
                            "query": {"type": "string"},
                        },
                    },
                },
            },
        ]


def call_tool(bundle: ReportToolBundle, name: str, arguments: dict[str, Any] | str) -> str:
    handlers = bundle.handlers()
    if name not in handlers:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    args = arguments
    if isinstance(arguments, str):
        args = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(args, dict):
        args = {}
    result = handlers[name](**args)
    return json.dumps(result, ensure_ascii=False, default=str)
