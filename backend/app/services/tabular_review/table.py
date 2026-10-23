"""In-memory sort and filter for a computed review table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.database.tabular_review import TabularReview, TabularReviewCell, TabularReviewRow


def cell_map(review: TabularReview) -> dict[tuple[int, int], TabularReviewCell]:
    return {(cell.row_id, cell.column_id): cell for cell in review.cells}


def _cell_similarity(cell: TabularReviewCell | None) -> float:
    if cell is None or cell.similarity is None:
        return -1.0
    return float(cell.similarity)


def sort_rows(
    rows: Sequence[TabularReviewRow],
    cells: Mapping[tuple[int, int], TabularReviewCell],
    *,
    sort_key: str,
    sort_dir: str,
) -> list[TabularReviewRow]:
    reverse = sort_dir == "desc"
    if sort_key.startswith("similarity:"):
        column_id = int(sort_key.split(":", 1)[1])
        return sorted(
            rows,
            key=lambda row: (_cell_similarity(cells.get((row.id, column_id))), row.title, row.id),
            reverse=reverse,
        )
    if sort_key.startswith("status:"):
        column_id = int(sort_key.split(":", 1)[1])
        return sorted(
            rows,
            key=lambda row: (
                (cells[(row.id, column_id)].status if (row.id, column_id) in cells else "no_hit"),
                row.title,
                row.id,
            ),
            reverse=reverse,
        )
    return sorted(rows, key=lambda row: (row.title.lower(), row.id), reverse=reverse)


def filter_rows(
    rows: Sequence[TabularReviewRow],
    cells: Mapping[tuple[int, int], TabularReviewCell],
    filters: Mapping[str, object],
) -> list[TabularReviewRow]:
    query = str(filters.get("q") or "").strip().lower()
    statuses = {str(item) for item in filters.get("statuses") or [] if item}
    column_id_raw = filters.get("column_id")
    column_id = int(column_id_raw) if column_id_raw is not None and column_id_raw != "" else None
    flagged = filters.get("flagged")
    locked = filters.get("locked")
    review_state = filters.get("review_state")
    kept: list[TabularReviewRow] = []
    for row in rows:
        if query and query not in row.title.lower():
            continue
        row_cells = [cell for (row_id, _), cell in cells.items() if row_id == row.id]
        if column_id is not None:
            row_cells = [cell for cell in row_cells if cell.column_id == column_id]
        if statuses and not any(cell.status in statuses for cell in row_cells):
            continue
        if flagged is True and not any(cell.flagged for cell in row_cells):
            continue
        if locked is True and not any(cell.locked for cell in row_cells):
            continue
        if review_state and not any(cell.review_state == review_state for cell in row_cells):
            continue
        kept.append(row)
    return kept
