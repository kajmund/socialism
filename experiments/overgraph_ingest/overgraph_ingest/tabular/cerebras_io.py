"""One GPT-OSS call per cell. No navigation and no second opinion."""

from __future__ import annotations

import json

from overgraph_ingest.cerebras.client import Completer
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.contract import STATUSES

SYSTEM = (
    "Answer one question about one contract from the listed TextUnits only. "
    "Return JSON with status, answer, source_unit_id, and excerpt. "
    "status is ANSWERED, UNCERTAIN, or NOT_FOUND. "
    "excerpt must be an exact substring of the chosen unit. "
    "Do not invent a unit id or quote."
)


def answer_with_cerebras(
    client: Completer,
    *,
    user_question: str,
    hits: list[SearchHit],
) -> dict[str, str]:
    payload = {
        "question": user_question,
        "units": [
            {"id": hit.key, "rank": hit.rank, "text": hit.text} for hit in hits
        ],
    }
    reply = client.complete(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
    )
    parsed = json.loads(reply.text)
    status = str(parsed.get("status") or "").strip().upper()
    if status not in STATUSES:
        raise ValueError(f"unsupported Cerebras status: {status}")
    return {
        "status": status,
        "answer": str(parsed.get("answer") or "").strip(),
        "source_unit_id": str(parsed.get("source_unit_id") or "").strip(),
        "excerpt": str(parsed.get("excerpt") or "").strip(),
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "seconds": reply.completion_seconds,
    }
