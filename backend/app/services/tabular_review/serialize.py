"""Serialize persisted reviews for the HTTP API."""

from __future__ import annotations

from app.database.tabular_review import (
    TabularReview,
    TabularReviewCell,
    TabularReviewCellEvent,
    TabularReviewColumn,
    TabularReviewRow,
    TabularReviewVerificationLabel,
)
from app.services.tabular_review.table import cell_map, filter_rows, sort_rows


def _dt(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def column_out(column: TabularReviewColumn) -> dict:
    return {
        "id": column.id,
        "title": column.title,
        "anchor_set_id": column.anchor_set_id,
        "label": column.label,
        "polarity": column.polarity,
        "allow_abstain": column.allow_abstain,
        "abstain_margin": column.abstain_margin,
        "sort_order": column.sort_order,
    }


def cell_out(cell: TabularReviewCell, *, include_candidates: bool = False) -> dict:
    candidates = []
    if include_candidates:
        candidates = [
            {
                "rank": item.rank,
                "text_unit_id": item.text_unit_id,
                "exact_text": item.exact_text,
                "similarity": item.similarity,
                "polarity": item.polarity,
                "source": item.source_json,
            }
            for item in cell.candidates
        ]
    return {
        "id": cell.id,
        "row_id": cell.row_id,
        "column_id": cell.column_id,
        "status": cell.status,
        "no_hit_reason": (
            (cell.source_json or {}).get("no_hit_reason")
            if cell.status in {"no_hit", "unknown"}
            else None
        ),
        "similarity": cell.similarity,
        "text_unit_id": cell.text_unit_id,
        "exact_text": cell.exact_text,
        "source": cell.source_json,
        "locked": cell.locked,
        "flagged": cell.flagged,
        "review_state": cell.review_state,
        "note": cell.note,
        "candidate_count": len(cell.candidates),
        "candidates": candidates,
    }


def row_out(row: TabularReviewRow, cells: list[TabularReviewCell], *, include_candidates: bool) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "document_version_id": row.document_version_id,
        "title": row.title,
        "source_object_id": row.source_object_id,
        "cells": [cell_out(cell, include_candidates=include_candidates) for cell in cells],
    }


def review_summary(review: TabularReview) -> dict:
    return {
        "id": review.id,
        "name": review.name,
        "document_count": len(review.rows) if review.rows is not None else 0,
        "column_count": len(review.columns) if review.columns is not None else 0,
        "score_threshold": review.score_threshold,
        "computed_at": _dt(review.computed_at),
        "updated_at": _dt(review.updated_at) or "",
        "created_at": _dt(review.created_at) or "",
    }


def review_out(review: TabularReview, *, include_candidates: bool = False) -> dict:
    cells = cell_map(review)
    visible = filter_rows(review.rows, cells, review.filter_json or {})
    ordered = sort_rows(visible, cells, sort_key=review.sort_key, sort_dir=review.sort_dir)
    rows = []
    for row in ordered:
        row_cells = [cells[key] for key in cells if key[0] == row.id]
        row_cells.sort(key=lambda cell: cell.column_id)
        rows.append(row_out(row, row_cells, include_candidates=include_candidates))
    return {
        "id": review.id,
        "name": review.name,
        "customer_id": review.customer_id,
        "score_threshold": review.score_threshold,
        "sort_key": review.sort_key,
        "sort_dir": review.sort_dir,
        "filter_json": review.filter_json,
        "computed_at": _dt(review.computed_at),
        "updated_at": _dt(review.updated_at) or "",
        "created_at": _dt(review.created_at) or "",
        "columns": [column_out(column) for column in review.columns],
        "rows": rows,
    }


def event_out(event: TabularReviewCellEvent) -> dict:
    return {
        "id": event.id,
        "action": event.action,
        "actor_user_id": event.actor_user_id,
        "payload": event.payload,
        "created_at": _dt(event.created_at) or "",
    }


def label_out(label: TabularReviewVerificationLabel) -> dict:
    return {
        "id": label.id,
        "label": label.label,
        "anchor_set_id": label.anchor_set_id,
        "text_unit_id": label.text_unit_id,
        "verdict": label.verdict,
        "activated_as_ssr_anchor": bool(label.activated_as_ssr_anchor),
        "created_at": _dt(label.created_at) or "",
    }
