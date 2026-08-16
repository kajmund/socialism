import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deleteRun, duplicateRun, listRuns } from "@/api/runs"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { formatRunDate } from "@/data/runs"
import type { RunStatus, RunSummary } from "@/data/runs-types"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

type RunCardProps = {
  run: RunSummary
  intl: string
  t: Translate
  onDelete: (id: number) => void
  onDuplicate: (id: number, name: string) => void
}

function statusLabel(status: RunStatus, t: Translate): string {
  switch (status) {
    case "done":
      return t("runs.status.done")
    case "running":
      return t("runs.status.running")
    case "draft":
      return t("runs.status.draft")
    case "failed":
      return t("runs.status.failed")
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function primaryResultsLabel(status: RunStatus, t: Translate): string {
  switch (status) {
    case "running":
      return t("runs.list.seeStatus")
    case "failed":
      return t("runs.list.seeError")
    default:
      return t("runs.list.openResults")
  }
}

function RunCard({ run, intl, t, onDelete, onDuplicate }: RunCardProps) {
  return (
    <div className="run-card">
      <Card className="relative h-full gap-0 rounded-[var(--radius-md)] py-4">
        <span className={"status-tag absolute right-4 top-4 " + run.status}>
          {statusLabel(run.status, t)}
        </span>
        <CardContent className="run-inner px-4">
          <div className="run-top">
            <div className="run-nm">{run.name}</div>
          </div>
          <div className="run-meta">
            {t("runs.list.population")} <b>{run.population}</b>
          </div>
          <div className="run-details">
            <div className="row">
              <span>{t("runs.list.ticks")}</span>
              <span className="v">{run.ticks}</span>
            </div>
            <div className="row">
              <span>{t("runs.list.variants")}</span>
              <span className="v">
                {run.variants > 1 ? (
                  <span className="variant-badges">
                    <span className="vb a">A</span>
                    <span className="vb b">B</span>
                  </span>
                ) : (
                  "1"
                )}
              </span>
            </div>
            <div className="row">
              <span>{t("runs.list.updated")}</span>
              <span className="v">{formatRunDate(run.updated, intl)}</span>
            </div>
          </div>
          <div className="run-actions">
            {run.status === "draft" ? (
              <Link className="primary full" to={`/runs/${run.id}/edit`}>
                {t("runs.list.continueConfig")}
              </Link>
            ) : (
              <>
                <Link
                  className="primary"
                  to={`/runs/${run.id}/edit?tab=results`}
                >
                  {primaryResultsLabel(run.status, t)}
                </Link>
                <Link to={`/runs/${run.id}/edit?tab=config`}>
                  {t("runs.list.configuration")}
                </Link>
              </>
            )}
            <button type="button" onClick={() => onDuplicate(run.id, run.name)}>
              {t("common.duplicate")}
            </button>
            <button type="button" onClick={() => onDelete(run.id)}>
              {t("common.delete")}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function RunListRow({ run, intl, t, onDelete, onDuplicate }: RunCardProps) {
  return (
    <div className="admin-list-row admin-list-runs">
      <div>
        <div className="nm">{run.name}</div>
        <div className="meta">{run.population}</div>
      </div>
      <span className={"status-tag " + run.status}>{statusLabel(run.status, t)}</span>
      <div className="cell">
        {t("runs.list.ticksDays", { count: run.ticks })}
      </div>
      <div className="cell">
        {run.variants > 1 ? t("runs.list.variantsAb") : t("runs.list.variantsOne")}
      </div>
      <div className="cell">{formatRunDate(run.updated, intl)}</div>
      <div className="admin-list-actions">
        {run.status === "draft" ? (
          <Link className="primary" to={`/runs/${run.id}/edit`}>
            {t("runs.list.continueConfig")}
          </Link>
        ) : (
          <Link className="primary" to={`/runs/${run.id}/edit?tab=results`}>
            {primaryResultsLabel(run.status, t)}
          </Link>
        )}
        <button type="button" onClick={() => onDuplicate(run.id, run.name)}>
          {t("common.duplicate")}
        </button>
        <button type="button" onClick={() => onDelete(run.id)}>
          {t("common.delete")}
        </button>
      </div>
    </div>
  )
}

export function RunsPage() {
  const { t, intl } = useLocale()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<"all" | RunStatus>("all")
  const [sort, setSort] = useState<"updated" | "ticks">("updated")
  const [view, setView] = useState<ListViewMode>("grid")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listRuns()
      .then((data) => {
        if (!cancelled) {
          setRuns(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("runs.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const list = useMemo(() => {
    let next = runs.filter(
      (r) =>
        r.name.toLowerCase().includes(query.toLowerCase()) &&
        (status === "all" || r.status === status),
    )
    if (sort === "updated") {
      next = [...next].sort(
        (a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime(),
      )
    }
    if (sort === "ticks") {
      next = [...next].sort((a, b) => b.ticks - a.ticks)
    }
    return next
  }, [runs, query, status, sort])

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2400)
  }

  async function handleDelete(id: number) {
    try {
      await deleteRun(id)
      setRuns((prev) => prev.filter((x) => x.id !== id))
      showToast(t("runs.list.deleted"))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  async function handleDuplicate(id: number, name: string) {
    try {
      const copy = await duplicateRun(id)
      setRuns((prev) => [copy, ...prev])
      showToast(t("runs.list.duplicated", { name }))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.duplicateError"))
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>{t("runs.list.title")}</h1>
            <p>{t("runs.list.intro")}</p>
          </div>
        </div>

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        <div className="controls-row">
          <div className="controls-left">
            <input
              className="dsearch"
              placeholder={t("runs.list.searchPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              className="dsel"
              value={status}
              onChange={(e) => setStatus(e.target.value as "all" | RunStatus)}
            >
              <option value="all">{t("runs.list.statusAll")}</option>
              <option value="done">{t("runs.list.statusDone")}</option>
              <option value="running">{t("runs.list.statusRunning")}</option>
              <option value="draft">{t("runs.list.statusDraft")}</option>
              <option value="failed">{t("runs.list.statusFailed")}</option>
            </select>
            <select
              className="dsel"
              value={sort}
              onChange={(e) => setSort(e.target.value as "updated" | "ticks")}
            >
              <option value="updated">{t("runs.list.sortUpdated")}</option>
              <option value="ticks">{t("runs.list.sortTicks")}</option>
            </select>
          </div>
          <div className="controls-right">
            <ViewToggle value={view} onChange={setView} />
            <Link
              to="/runs/new"
              className="admin-cta inline-flex h-9 items-center rounded-[var(--radius-md)] bg-db-black px-[18px] text-[0.85rem] text-db-ink-0 no-underline hover:bg-db-ink-800"
            >
              {t("runs.list.newRun")}
            </Link>
          </div>
        </div>

        {loading ? (
          <div className="no-match">{t("runs.list.loading")}</div>
        ) : list.length === 0 ? (
          <div className="no-match">{t("runs.list.emptyFilter")}</div>
        ) : view === "grid" ? (
          <div className="run-grid">
            {list.map((run) => (
              <RunCard
                key={run.id}
                run={run}
                intl={intl}
                t={t}
                onDelete={handleDelete}
                onDuplicate={handleDuplicate}
              />
            ))}
          </div>
        ) : (
          <div className="admin-list-stack">
            {list.map((run) => (
              <RunListRow
                key={run.id}
                run={run}
                intl={intl}
                t={t}
                onDelete={handleDelete}
                onDuplicate={handleDuplicate}
              />
            ))}
          </div>
        )}
      </div>

      {toast && (
        <div className="fixed bottom-6 right-6 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
