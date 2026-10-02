"""Measures window candidates and explicitly labeled contradiction pairs."""

from dataclasses import replace
import json

from app.config import settings
from app.jev.system import JevSystemOne
from app.services.research.assessment import AssessableEvidence
from tests.research_reuse.jev_passages import measure, requests
from tests.research_reuse.jev_windows import CRITERIA, aggregate, contradiction_requests, plan


async def variant(
    client: JevSystemOne, items: list[AssessableEvidence], report: dict, name: str,
) -> None:
    row = {"variant": name, "status": "incomplete", "calls": []}
    report["runs"].append(row)
    passages = []
    if name == "compact_rank":
        batches = requests(items, objective=report["question"], variant="compact",
            max_state_chars=report["state_budget"])
        batches = [replace(batch,
            questions={k: v for k, v in batch.questions.items() if k in CRITERIA},
            bindings={k: v for k, v in batch.bindings.items() if k in CRITERIA},
        ) for batch in batches]
    else:
        field = "excerpt" if name == "excerpt_windows" else "source"
        batches, passages = plan(items, objective=report["question"], field=field,
            max_state_chars=report["state_budget"])
        row["coverage"] = [{
            "evidence_id": p.evidence_id, "passage_id": p.id, "field": p.field,
            "start": p.start, "end": p.end, "source_sha256": p.row["source_text_sha256"],
            "context_start": p.context_start, "context_end": p.context_end,
            "content_hash": p.row["content_hash"],
        } for p in passages]
    result = await measure(client, batches, model=report["model"],
        concurrency=report["concurrency"], timeout_seconds=settings.research_jev_timeout_seconds,
        journal=row["calls"])
    row.update(result)
    if passages:
        row["passage_scores"] = row["scores"]
        row["scores"] = aggregate(row["passage_scores"], passages)
        row["passage_count"] = len(passages)
        row["covered_chars"] = sum(p.end - p.start for p in passages)
    row["evidence_count"] = len(row["scores"])
    row["status"] = "completed"


async def pair_control(
    client: JevSystemOne, items: list[AssessableEvidence], report: dict,
) -> None:
    row = {"variant": "separate_contradiction", "status": "incomplete", "calls": []}
    report["runs"].append(row)
    batches = contradiction_requests(items, report["question"])
    if any(len(json.dumps(b.state, ensure_ascii=False)) > report["state_budget"] for b in batches):
        raise ValueError("Complete candidate fact pair exceeds the explicit state budget")
    row.update(await measure(client, batches,
        model=report["model"], concurrency=report["concurrency"],
        timeout_seconds=settings.research_jev_timeout_seconds, journal=row["calls"]))
    row["status"] = "completed"
