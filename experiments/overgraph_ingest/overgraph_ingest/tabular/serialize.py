"""Machine-readable cell payloads."""

from __future__ import annotations

from dataclasses import asdict

from overgraph_ingest.tabular.contract import CellResult


def cell_payload(result: CellResult) -> dict[str, object]:
    return {
        "document_id": result.document_id,
        "relative_path": result.relative_path,
        "question_id": result.question_id,
        "question": result.question,
        "variant": result.variant,
        "status": result.status,
        "answer": result.answer,
        "source_unit_ids": result.source_unit_ids,
        "sources": [asdict(item) for item in result.sources],
        "navigation_steps": result.navigation_steps,
        "units_examined": result.units_examined,
        "jev_calls": result.jev_calls,
        "cerebras_calls": result.cerebras_calls,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "retrieve_seconds": result.retrieve_seconds,
        "classify_seconds": result.classify_seconds,
        "navigate_seconds": result.navigate_seconds,
        "answer_seconds": result.answer_seconds,
        "cell_seconds": result.cell_seconds,
        "retrieval": result.retrieval,
        "navigation": result.navigation,
        "budget_exhausted": result.budget_exhausted,
        "notes": result.notes,
        "citation_validated": all(item.validated for item in result.sources)
        if result.sources
        else False,
    }
