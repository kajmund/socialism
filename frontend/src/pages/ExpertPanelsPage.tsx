import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  deletePopulation,
  duplicatePopulation,
  listPopulations,
} from "@/api/populations"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { formatLibraryDate } from "@/data/library"
import type { PopulationSummary } from "@/data/library-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

const CTA_CLASS =
  "admin-cta inline-flex h-9 items-center rounded-[var(--radius-md)] bg-db-black px-[18px] text-[0.85rem] text-db-ink-0 no-underline hover:bg-db-ink-800"

type PanelItemProps = {
  panel: PopulationSummary
  intl: string
  t: Translate
  onDelete: (id: number) => void
  onDup: (id: number) => void
}

function PanelCard({ panel, intl, t, onDelete, onDup }: PanelItemProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{panel.name}</div>
          </div>
          <div className="meta-line">
            {t("expertPanels.list.metaLine", {
              count: panel.size,
              when: formatLibraryDate(panel.updated, intl),
            })}
          </div>
          {confirming ? (
            <div className="confirm-row" style={{ marginTop: "auto" }}>
              <button type="button" style={{ flex: 1 }} onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(panel.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/bolag/expertpaneler/${panel.id}`}>
                {t("common.open")}
              </Link>
              <button type="button" onClick={() => onDup(panel.id)}>
                {t("common.duplicate")}
              </button>
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                {t("common.delete")}
              </button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PanelListRow({ panel, intl, t, onDelete, onDup }: PanelItemProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="admin-list-row admin-list-pops">
      <div>
        <div className="nm">{panel.name}</div>
        <div className="meta">
          {t("expertPanels.list.metaLine", {
            count: panel.size,
            when: formatLibraryDate(panel.updated, intl),
          })}
        </div>
      </div>
      <div className="cell">{panel.size}</div>
      <div className="admin-list-actions">
        {confirming ? (
          <>
            <button type="button" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </button>
            <button type="button" className="primary" onClick={() => onDelete(panel.id)}>
              {t("common.deleteConfirm")}
            </button>
          </>
        ) : (
          <>
            <Link className="primary" to={`/bolag/expertpaneler/${panel.id}`}>
              {t("common.open")}
            </Link>
            <button type="button" onClick={() => onDup(panel.id)}>
              {t("common.duplicate")}
            </button>
            <button type="button" onClick={() => setConfirming(true)}>
              {t("common.delete")}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export function ExpertPanelsPage() {
  const { t, intl } = useLocale()
  const [panels, setPanels] = useState<PopulationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [view, setView] = useState<ListViewMode>("grid")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void listPopulations({ kind: "expert_panel" })
      .then((rows) => {
        if (!cancelled) {
          setPanels(rows)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("expertPanels.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2400)
    return () => window.clearTimeout(timer)
  }, [toast])

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return panels
      .filter((row) => !q || row.name.toLowerCase().includes(q))
      .sort((a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime())
  }, [panels, query])

  async function handleDelete(id: number) {
    try {
      await deletePopulation(id)
      setPanels((prev) => prev.filter((row) => row.id !== id))
      setToast(t("expertPanels.list.deleted"))
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  async function handleDuplicate(id: number) {
    try {
      const copy = await duplicatePopulation(id)
      setPanels((prev) => [copy, ...prev])
      setToast(t("expertPanels.list.duplicated", { name: copy.name }))
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("common.duplicateError"))
    }
  }

  return (
    <div className="wrap">
      <div className="head-row">
        <div>
          <h1>{t("expertPanels.list.title")}</h1>
          <p>{t("expertPanels.list.intro")}</p>
        </div>
      </div>

      {error ? (
        <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="no-match">{t("expertPanels.list.loading")}</div>
      ) : panels.length > 0 ? (
        <>
          <div className="controls-row">
            <div className="controls-left">
              <input
                className="dsearch"
                placeholder={t("expertPanels.list.searchPlaceholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="controls-right">
              <ViewToggle value={view} onChange={setView} />
              <Link to="/bolag/expertpaneler/new" className={CTA_CLASS}>
                {t("expertPanels.list.newPanel")}
              </Link>
            </div>
          </div>
          {list.length === 0 ? (
            <div className="no-match">{t("expertPanels.list.emptyFilter", { query })}</div>
          ) : view === "grid" ? (
            <div className="pop-grid">
              {list.map((panel) => (
                <PanelCard
                  key={panel.id}
                  panel={panel}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                  onDup={(id) => void handleDuplicate(id)}
                />
              ))}
            </div>
          ) : (
            <div className="admin-list-stack">
              {list.map((panel) => (
                <PanelListRow
                  key={panel.id}
                  panel={panel}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                  onDup={(id) => void handleDuplicate(id)}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <h2 style={{ font: "var(--text-h2)", marginBottom: 10 }}>
            {t("expertPanels.list.emptyTitle")}
          </h2>
          <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>
            {t("expertPanels.list.emptyBody")}
          </p>
          <Link to="/bolag/expertpaneler/new" className={CTA_CLASS}>
            {t("expertPanels.list.newPanel")}
          </Link>
        </div>
      )}

      {toast ? (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      ) : null}
    </div>
  )
}
