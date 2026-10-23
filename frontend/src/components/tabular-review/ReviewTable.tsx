import { useMemo, useRef, useState } from "react"
import type { TabularReview, TabularReviewCell, TabularReviewRow } from "@/api/tabularReviews"
import { formatSimilarity } from "@/components/tabular-review/scoreFormat"
import { REVIEW_ROW_HEIGHT, visibleRowWindow } from "@/components/tabular-review/virtualRows"
import { useLocale } from "@/i18n"

type Props = {
  review: TabularReview
  onOpenCell: (row: TabularReviewRow, cell: TabularReviewCell) => void
  onSort: (sortKey: string) => void
}

function statusKey(status: TabularReviewCell["status"]) {
  switch (status) {
    case "hit":
      return "tabularReview.status.hit" as const
    case "no_hit":
      return "tabularReview.status.noHit" as const
    case "unknown":
      return "tabularReview.status.unknown" as const
    case "negative_hit":
      return "tabularReview.status.negativeHit" as const
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function sortMark(active: boolean, dir: TabularReview["sort_dir"]) {
  if (!active) return ""
  return dir === "asc" ? " ↑" : " ↓"
}

export function ReviewTable({ review, onOpenCell, onSort }: Props) {
  const { t, locale } = useLocale()
  const scroller = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewport, setViewport] = useState(480)
  const window = useMemo(
    () => visibleRowWindow(scrollTop, viewport, review.rows.length),
    [scrollTop, viewport, review.rows.length],
  )
  const slice = review.rows.slice(window.start, window.end)

  return (
    <div
      ref={scroller}
      className="min-h-0 flex-1 overflow-auto"
      onScroll={(event) => {
        setScrollTop(event.currentTarget.scrollTop)
        setViewport(event.currentTarget.clientHeight)
      }}
    >
      <div style={{ height: review.rows.length * REVIEW_ROW_HEIGHT }}>
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-[color:var(--bg-chrome)]">
            <tr>
              <th className="border-b px-3 py-2 text-left">
                <button
                  type="button"
                  className="text-left font-medium"
                  aria-label={t("tabularReview.table.sortByTitle")}
                  onClick={() => onSort("document_title")}
                >
                  {t("tabularReview.table.document")}
                  {sortMark(review.sort_key === "document_title", review.sort_dir)}
                </button>
              </th>
              {review.columns.map((column) => {
                const sortKey = `similarity:${column.id}`
                return (
                  <th key={column.id} className="border-b px-3 py-2 text-left">
                    <button
                      type="button"
                      className="text-left font-medium"
                      aria-label={t("tabularReview.table.sortBySimilarity", { title: column.title })}
                      onClick={() => onSort(sortKey)}
                    >
                      {column.title}
                      {sortMark(review.sort_key === sortKey, review.sort_dir)}
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {window.start > 0 ? (
              <tr aria-hidden="true">
                <td colSpan={review.columns.length + 1} style={{ height: window.start * REVIEW_ROW_HEIGHT }} />
              </tr>
            ) : null}
            {slice.map((row) => (
              <tr key={row.id} style={{ height: REVIEW_ROW_HEIGHT }}>
                <th className="border-b px-3 py-2 text-left align-top">{row.title}</th>
                {review.columns.map((column) => {
                  const cell = row.cells.find((item) => item.column_id === column.id)
                  if (!cell) {
                    return (
                      <td key={column.id} className="border-b px-3 py-2 text-muted-foreground">
                        {t("tabularReview.status.noHit")}
                      </td>
                    )
                  }
                  return (
                    <td key={column.id} className="border-b px-3 py-2 align-top">
                      <button
                        type="button"
                        className="w-full text-left"
                        onClick={() => onOpenCell(row, cell)}
                      >
                        <span className="block font-medium">{t(statusKey(cell.status))}</span>
                        {cell.status === "no_hit" ? null : (
                          <span className="block line-clamp-2 text-xs">{cell.exact_text}</span>
                        )}
                        <span className="block text-xs text-muted-foreground">
                          {t("tabularReview.cell.similarity", {
                            score: formatSimilarity(cell.similarity, locale),
                          })}
                        </span>
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
