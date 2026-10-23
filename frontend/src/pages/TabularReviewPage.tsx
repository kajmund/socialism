import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { listAnchorSets, type SsrAnchorSet } from "@/api/anchorSets"
import {
  addTabularReviewColumn,
  approveTabularReviewCell,
  createTabularReview,
  deleteTabularReviewColumn,
  flagTabularReviewCell,
  getTabularReview,
  listTabularReviewDocuments,
  lockTabularReviewCell,
  noteTabularReviewCell,
  rejectTabularReviewCell,
  runTabularReview,
  updateTabularReview,
  type TabularReview,
  type TabularReviewCell,
  type TabularReviewDocument,
  type TabularReviewRow,
} from "@/api/tabularReviews"
import { AdminShell } from "@/components/layout/AdminShell"
import { ReviewMode } from "@/components/tabular-review/ReviewMode"
import { ReviewTable } from "@/components/tabular-review/ReviewTable"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

function replaceCell(review: TabularReview, cell: TabularReviewCell): TabularReview {
  return {
    ...review,
    rows: review.rows.map((row) =>
      row.id === cell.row_id
        ? { ...row, cells: row.cells.map((item) => (item.id === cell.id ? { ...item, ...cell } : item)) }
        : row,
    ),
  }
}

export function TabularReviewPage() {
  const { t } = useLocale()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isNew = id === "new"
  const reviewId = isNew ? null : Number(id)

  const [name, setName] = useState("")
  const [threshold, setThreshold] = useState(0.35)
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [review, setReview] = useState<TabularReview | null>(null)
  const [documents, setDocuments] = useState<TabularReviewDocument[]>([])
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [sets, setSets] = useState<SsrAnchorSet[]>([])
  const [newSetId, setNewSetId] = useState("")
  const [newLabel, setNewLabel] = useState("")
  const [newTitle, setNewTitle] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<{ row: TabularReviewRow; cell: TabularReviewCell } | null>(null)

  const clauseSets = useMemo(() => sets.filter((item) => item.kind === "clause"), [sets])
  const selectedSet = clauseSets.find((item) => String(item.id) === newSetId)
  const openColumn = review && open ? review.columns.find((column) => column.id === open.cell.column_id) : null

  useEffect(() => {
    let cancelled = false
    Promise.all([listTabularReviewDocuments(), listAnchorSets({ kind: "clause" })])
      .then(([docs, anchors]) => {
        if (cancelled) return
        setDocuments(docs)
        setSets(anchors)
        if (anchors[0]) setNewSetId(String(anchors[0].id))
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("tabularReview.editor.loadError"))
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (reviewId == null || Number.isNaN(reviewId)) return
    let cancelled = false
    getTabularReview(reviewId)
      .then((item) => {
        if (cancelled) return
        setReview(item)
        setName(item.name)
        setThreshold(item.score_threshold)
        setSelectedDocs(item.rows.map((row) => row.document_id))
        setQuery(String(item.filter_json.q ?? ""))
        setStatusFilter(String((item.filter_json.statuses as string[] | undefined)?.[0] ?? ""))
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("tabularReview.editor.loadError"))
      })
    return () => {
      cancelled = true
    }
  }, [reviewId, t])

  async function saveNew() {
    setBusy(true)
    setError(null)
    try {
      const created = await createTabularReview({
        name,
        document_ids: selectedDocs,
        score_threshold: threshold,
      })
      navigate(`/tabular-review/${created.id}`, { replace: true })
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setBusy(false)
    }
  }

  async function persistFilters(nextQuery: string, nextStatus: string) {
    if (!review) return
    const updated = await updateTabularReview(review.id, {
      name,
      score_threshold: threshold,
      filter_json: {
        q: nextQuery,
        statuses: nextStatus ? [nextStatus] : [],
      },
    })
    setReview(updated)
  }

  async function persistSort(sortKey: string) {
    if (!review) return
    const same = review.sort_key === sortKey
    const updated = await updateTabularReview(review.id, {
      sort_key: sortKey,
      sort_dir: same && review.sort_dir === "desc" ? "asc" : "desc",
    })
    setReview(updated)
  }

  async function run() {
    if (!review) return
    setBusy(true)
    try {
      const updated = await updateTabularReview(review.id, {
        name,
        document_ids: selectedDocs,
        score_threshold: threshold,
      })
      const computed = await runTabularReview(updated.id)
      setReview(computed)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("tabularReview.editor.runError"))
    } finally {
      setBusy(false)
    }
  }

  async function addColumn() {
    if (!review || !selectedSet || !newLabel) return
    setBusy(true)
    try {
      const updated = await addTabularReviewColumn(review.id, {
        title: newTitle || newLabel,
        anchor_set_id: selectedSet.id,
        label: newLabel,
      })
      setReview(updated)
      setNewTitle("")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.addError"))
    } finally {
      setBusy(false)
    }
  }

  async function removeColumn(columnId: number) {
    if (!review) return
    await deleteTabularReviewColumn(review.id, columnId)
    setReview(await getTabularReview(review.id))
  }

  async function act(action: () => Promise<TabularReviewCell>) {
    if (!review) return
    setBusy(true)
    try {
      const cell = await action()
      setReview(replaceCell(review, cell))
      setOpen((current) => (current && current.cell.id === cell.id ? { ...current, cell: { ...current.cell, ...cell } } : current))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AdminShell>
      <div className="wrap admin-page">
        <div className="admin-page-chrome space-y-3">
          <p className="text-sm text-muted-foreground">
            <Link to="/tabular-review">{t("tabularReview.list.title")}</Link>
          </p>
          <div className="head-row">
            <div>
              <h1>{isNew ? t("tabularReview.editor.newTitle") : name || t("tabularReview.editor.editTitle")}</h1>
              <p className="muted">{t("tabularReview.editor.intro")}</p>
            </div>
          </div>
          {error ? <p className="text-destructive">{error}</p> : null}
          <div className="flex flex-wrap items-end gap-3">
            <label className="space-y-1">
              <span className="text-sm">{t("tabularReview.editor.name")}</span>
              <input className="dsearch" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-sm">{t("tabularReview.editor.threshold")}</span>
              <input
                className="dsearch w-24"
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={threshold}
                onChange={(event) => setThreshold(Number(event.target.value))}
              />
            </label>
            {isNew ? (
              <AdminButton type="button" variant="primary" disabled={busy || !name} onClick={() => void saveNew()}>
                {t("common.save")}
              </AdminButton>
            ) : (
              <AdminButton type="button" variant="primary" disabled={busy} onClick={() => void run()}>
                {busy ? t("tabularReview.editor.running") : t("tabularReview.editor.run")}
              </AdminButton>
            )}
          </div>
          <div className="flex flex-wrap gap-3">
            <label className="space-y-1">
              <span className="text-sm">{t("tabularReview.editor.search")}</span>
              <input
                className="dsearch"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  if (review) void persistFilters(event.target.value, statusFilter)
                }}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm">{t("tabularReview.editor.statusFilter")}</span>
              <select
                className="dsel"
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value)
                  if (review) void persistFilters(query, event.target.value)
                }}
              >
                <option value="">{t("tabularReview.editor.allStatuses")}</option>
                <option value="hit">{t("tabularReview.status.hit")}</option>
                <option value="no_hit">{t("tabularReview.status.noHit")}</option>
                <option value="unknown">{t("tabularReview.status.unknown")}</option>
                <option value="negative_hit">{t("tabularReview.status.negativeHit")}</option>
              </select>
            </label>
          </div>
          <details className="rounded border p-3">
            <summary className="cursor-pointer text-sm font-medium">{t("tabularReview.editor.documents")}</summary>
            <div className="mt-2 max-h-48 space-y-1 overflow-auto">
              {documents.map((doc) => (
                <label key={doc.document_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.document_id)}
                    onChange={(event) => {
                      setSelectedDocs((prev) =>
                        event.target.checked ? [...prev, doc.document_id] : prev.filter((id) => id !== doc.document_id),
                      )
                    }}
                  />
                  {doc.title}
                </label>
              ))}
              {documents.length === 0 ? <p className="muted text-sm">{t("tabularReview.editor.noDocuments")}</p> : null}
            </div>
          </details>
          {review ? (
            <div className="flex flex-wrap items-end gap-2">
              <select className="dsel" value={newSetId} onChange={(event) => setNewSetId(event.target.value)}>
                {clauseSets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <select className="dsel" value={newLabel} onChange={(event) => setNewLabel(event.target.value)}>
                <option value="">{t("tabularReview.editor.chooseLabel")}</option>
                {selectedSet?.labels.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
              <input
                className="dsearch"
                placeholder={t("tabularReview.editor.columnTitle")}
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
              />
              <AdminButton type="button" disabled={busy || !newLabel} onClick={() => void addColumn()}>
                {t("tabularReview.editor.addColumn")}
              </AdminButton>
              {review.columns.map((column) => (
                <AdminButton key={column.id} type="button" onClick={() => void removeColumn(column.id)}>
                  {t("tabularReview.editor.removeColumn", { title: column.title })}
                </AdminButton>
              ))}
            </div>
          ) : null}
        </div>
        <div className="admin-page-body flex min-h-0 flex-col">
          {review && open && openColumn ? (
            <ReviewMode
              review={review}
              row={open.row}
              cell={open.cell}
              column={openColumn}
              busy={busy}
              onClose={() => setOpen(null)}
              onApprove={() => void act(() => approveTabularReviewCell(review.id, open.cell.id))}
              onReject={() => void act(() => rejectTabularReviewCell(review.id, open.cell.id))}
              onFlag={() => void act(() => flagTabularReviewCell(review.id, open.cell.id))}
              onLock={() => void act(() => lockTabularReviewCell(review.id, open.cell.id))}
              onNote={(value) => void act(() => noteTabularReviewCell(review.id, open.cell.id, value))}
            />
          ) : review ? (
            <ReviewTable
              review={review}
              onOpenCell={(row, cell) => setOpen({ row, cell })}
              onSort={(sortKey) => void persistSort(sortKey)}
            />
          ) : (
            <p className="muted">{t("tabularReview.editor.hint")}</p>
          )}
        </div>
      </div>
    </AdminShell>
  )
}
