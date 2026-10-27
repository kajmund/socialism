import { useEffect, useState } from "react"
import type {
  TabularReview,
  TabularReviewCell,
  TabularReviewColumn,
  TabularReviewEvent,
  TabularReviewRow,
} from "@/api/tabularReviews"
import { tabularReviewCellHistory } from "@/api/tabularReviews"
import { getUnderlagFile } from "@/api/underlag"
import { PdfKnowledgeViewer } from "@/components/underlag/PdfKnowledgeViewer"
import { formatSimilarity } from "@/components/tabular-review/scoreFormat"
import { sourcePage, sourceToFocusAnchor } from "@/components/tabular-review/sourceAnchor"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey } from "@/i18n"

type Props = {
  review: TabularReview
  row: TabularReviewRow
  cell: TabularReviewCell
  column: TabularReviewColumn
  busy: boolean
  onClose: () => void
  onApprove: () => void
  onReject: () => void
  onFlag: () => void
  onLock: () => void
  onNote: (note: string) => void
}

const HISTORY_ACTION_KEYS = {
  locked: "tabularReview.historyAction.locked",
  flagged: "tabularReview.historyAction.flagged",
  review_state: "tabularReview.historyAction.review_state",
  note: "tabularReview.historyAction.note",
  verification_label: "tabularReview.historyAction.verification_label",
  update: "tabularReview.historyAction.update",
} as const satisfies Record<string, MessageKey>

function historyActionLabel(t: (key: MessageKey) => string, action: string): string {
  if (action in HISTORY_ACTION_KEYS) {
    return t(HISTORY_ACTION_KEYS[action as keyof typeof HISTORY_ACTION_KEYS])
  }
  return action
}

function cellStatusKey(status: TabularReviewCell["status"]) {
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

export function ReviewMode({
  review,
  row,
  cell,
  column,
  busy,
  onClose,
  onApprove,
  onReject,
  onFlag,
  onLock,
  onNote,
}: Props) {
  const { t, locale, intl } = useLocale()
  const [note, setNote] = useState(cell.note ?? "")
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [history, setHistory] = useState<TabularReviewEvent[]>([])

  useEffect(() => {
    setNote(cell.note ?? "")
  }, [cell.note, cell.id])

  useEffect(() => {
    let cancelled = false
    tabularReviewCellHistory(review.id, cell.id)
      .then((events) => {
        if (!cancelled) setHistory(events)
      })
      .catch(() => {
        if (!cancelled) setHistory([])
      })
    return () => {
      cancelled = true
    }
  }, [review.id, cell.id, cell.review_state, cell.locked, cell.flagged, cell.note])

  useEffect(() => {
    const sourceId = row.source_object_id
    if (!sourceId) {
      setPdfUrl(null)
      return
    }
    let objectUrl: string | null = null
    let cancelled = false
    getUnderlagFile(sourceId)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setPdfUrl(objectUrl)
        setPdfError(null)
      })
      .catch(() => {
        if (!cancelled) setPdfError(t("tabularReview.review.missingPdf"))
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [row.source_object_id, t])

  const focus = sourceToFocusAnchor(cell.source)
  const page = sourcePage(cell.source)
  const fallback = !focus?.rects.length && page
    ? t("tabularReview.review.pageFallback", { page })
    : !page
      ? t("tabularReview.review.clauseFallback", { clause: cell.source.locator || "—" })
      : null

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(280px,38%)_1fr]">
      <aside className="min-h-0 overflow-auto rounded border border-[color:var(--border-hairline)] p-4">
        <div className="mb-3 flex items-start justify-between gap-2">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{review.name}</p>
            <h2 className="text-lg font-medium">{row.title}</h2>
            <p className="text-sm text-muted-foreground">{column.title}</p>
          </div>
          <AdminButton type="button" onClick={onClose}>
            {t("common.close")}
          </AdminButton>
        </div>
        <p className="text-sm">{t(cellStatusKey(cell.status))}</p>
        <p className="text-sm text-muted-foreground">
          {t("tabularReview.cell.similarity", { score: formatSimilarity(cell.similarity, locale) })}
        </p>
        {cell.status === "no_hit" ? (
          <p className="mt-3 text-sm">{t("tabularReview.status.noHit")}</p>
        ) : (
          <blockquote className="mt-3 whitespace-pre-wrap text-sm">{cell.exact_text}</blockquote>
        )}
        {fallback ? <p className="mt-2 text-xs text-muted-foreground">{fallback}</p> : null}
        {cell.candidates.length > 1 ? (
          <details className="mt-3">
            <summary className="cursor-pointer text-sm">{t("tabularReview.review.moreCandidates")}</summary>
            <ul className="mt-2 space-y-2">
              {cell.candidates.map((candidate) => (
                <li key={candidate.text_unit_id} className="rounded border p-2 text-sm">
                  <p className="text-xs text-muted-foreground">
                    {t("tabularReview.cell.similarity", {
                      score: formatSimilarity(candidate.similarity, locale),
                    })}
                  </p>
                  <p>{candidate.exact_text}</p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-2">
          <AdminButton type="button" variant="primary" disabled={busy || !cell.text_unit_id} onClick={onApprove}>
            {t("tabularReview.actions.approve")}
          </AdminButton>
          <AdminButton type="button" disabled={busy || !cell.text_unit_id} onClick={onReject}>
            {t("tabularReview.actions.reject")}
          </AdminButton>
          <AdminButton type="button" disabled={busy} onClick={onFlag}>
            {cell.flagged ? t("tabularReview.actions.unflag") : t("tabularReview.actions.flag")}
          </AdminButton>
          <AdminButton type="button" disabled={busy} onClick={onLock}>
            {cell.locked ? t("tabularReview.actions.unlock") : t("tabularReview.actions.lock")}
          </AdminButton>
        </div>
        <label className="mt-4 block space-y-1">
          <span className="text-sm">{t("tabularReview.actions.note")}</span>
          <textarea className="dsearch min-h-[80px] w-full" value={note} onChange={(event) => setNote(event.target.value)} />
          <AdminButton type="button" disabled={busy} onClick={() => onNote(note)}>
            {t("tabularReview.actions.saveNote")}
          </AdminButton>
        </label>
        <section className="mt-4">
          <h3 className="text-sm font-medium">{t("tabularReview.review.history")}</h3>
          {history.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">{t("tabularReview.review.historyEmpty")}</p>
          ) : (
            <ol className="mt-2 space-y-1 text-xs text-muted-foreground">
              {history.map((event) => (
                <li key={event.id}>
                  {historyActionLabel(t, event.action)}
                  {" · "}
                  {new Intl.DateTimeFormat(intl, { dateStyle: "short", timeStyle: "short" }).format(
                    new Date(event.created_at),
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>
      </aside>
      <section className="min-h-0 overflow-hidden rounded border border-[color:var(--border-hairline)]">
        {pdfError ? <p className="p-4 text-sm text-destructive">{pdfError}</p> : null}
        {!row.source_object_id ? (
          <p className="p-4 text-sm text-muted-foreground">{t("tabularReview.review.missingPdf")}</p>
        ) : null}
        {pdfUrl ? (
          <PdfKnowledgeViewer
            url={pdfUrl}
            focusAnchors={focus ? [focus] : []}
            selectionActive={false}
            onSelection={() => undefined}
            onClearSelection={() => undefined}
            onError={setPdfError}
            pageNumber={page}
          />
        ) : null}
      </section>
    </div>
  )
}
