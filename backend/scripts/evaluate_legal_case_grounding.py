"""Opt-in live evaluation of final-court attribution on two manually reviewed cases.

Run from backend with PYTHONPATH=. and configured DB/LLM/MCP access. Uses active
customer/module prompts, public case texts, and no research-attempt writes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import app.services.execution  # noqa: F401 -- register execution ORM relationships
from app.database.session import engine
from app.llm.legal_research import LegalDomainExtractionError, LlmLegalInterpreter
from app.services.knowledge.models import KnowledgeScope
from app.services.lagen_nu.mcp_client import OfficialLagenNuMcpClient
from app.services.legal_research_result import LegalResearchResult, LegalSourceIdentity
from app.services.research.models import ResearchContext

QUESTION = (
    "Vilka avgöranden från Högsta domstolen finns där 36 § avtalslagen var den "
    "avgörande grunden för utgången och där domstolen uttryckligen redovisade vilka "
    "omständigheter som tillmättes tyngst vid oskälighetsbedömningen, utöver "
    "NJA 1983 s. 332 och NJA 1989 s. 346?"
)
# Boundaries reviewed against public full texts, not inferred by the model under test.
CASES = {
    "1999s408": {
        "start": "HD (JustR:n Gregow, Lind och Pripp) beslöt följande dom:",
        "end": "Referenten JustR Lars K Beckman, med vilken JustR Nyström instämde, var skiljaktig",
        "supports": True,
    },
    "2010s467": {
        "start": "HD (justitieråden Leif Thorsson, Severin Blomstrand, Torgny Håstad",
        "end": "Justitierådet Agneta Bäcklund var skiljaktig",
        "supports": False,
    },
}


def check_result(case: str, raw: str, result: LegalResearchResult) -> dict[str, bool]:
    expected = CASES[case]
    start = raw.index(expected["start"])
    end = raw.index(expected["end"], start)
    majority = raw[start:end]
    analysis = result.case_law
    holding = analysis.authoritative_holding if analysis else None
    return {
        "relation": result.relation.relation
        in ({"supports"} if expected["supports"] else {"contextual", "limits", "irrelevant"}),
        "identified_supreme_holding": holding is not None and holding.court_level == "supreme",
        "adjustment": holding is not None and holding.adjustment_granted is expected["supports"],
        "decision_basis": holding is not None
        and (
            holding.decision_basis == "statutory_adjustment"
            if expected["supports"]
            else holding.decision_basis == "other"
        ),
        "majority_grounding": holding is not None
        and bool(holding.citations)
        and all(bool(c.quote.strip()) and c.quote in majority for c in holding.citations),
        "decisive_factors": bool(analysis and analysis.decisive_factors)
        if expected["supports"]
        else True,
    }


async def evaluate(customer_id: int, module: str, output: Path) -> bool:
    client = OfficialLagenNuMcpClient()
    context = ResearchContext(scope=KnowledgeScope(customer_id=customer_id, module=module))
    rows = []
    try:
        for case in CASES:
            uri = "https://lagen.nu/dom/nja/" + case
            started = time.perf_counter()
            document = await client.get_document(uri, max_chars=200000)
            if document.truncated:
                raise ValueError(f"Evaluation requires complete text: {uri}")
            try:
                result = await LlmLegalInterpreter().interpret(
                    source=LegalSourceIdentity(
                        kind="case_law", canonical_uri=uri, title=document.title
                    ),
                    question=QUESTION,
                    raw_text=document.text,
                    truncated=False,
                    context=context,
                )
            except LegalDomainExtractionError as exc:
                rows.append(
                    {
                        "source": uri,
                        "passed": False,
                        "sha256": hashlib.sha256(document.text.encode()).hexdigest(),
                        "seconds": round(time.perf_counter() - started, 2),
                        "failure": str(exc),
                        "category": exc.category,
                    }
                )
                continue
            checks = check_result(case, document.text, result)
            rows.append(
                {
                    "source": uri,
                    "sha256": hashlib.sha256(document.text.encode()).hexdigest(),
                    "seconds": round(time.perf_counter() - started, 2),
                    "checks": checks,
                    "passed": all(checks.values()),
                    "analysis": result.model_dump(mode="json", exclude={"raw_text"}),
                }
            )
        payload = {"question": QUESTION, "cases": rows, "passed": all(r["passed"] for r in rows)}
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "passed": payload["passed"],
                    "cases": [{k: v for k, v in row.items() if k != "analysis"} for row in rows],
                },
                ensure_ascii=False,
            )
        )
        return payload["passed"]
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-id", type=int, required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(evaluate(args.customer_id, args.module, args.output)) else 1)
