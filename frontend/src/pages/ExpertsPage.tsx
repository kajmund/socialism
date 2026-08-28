import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deletePersona, listExpertPersonas } from "@/api/personas"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { formatLibraryDate, personaInitials } from "@/data/library"
import type { LibraryPersona } from "@/data/library-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

const CTA_CLASS =
  "admin-cta inline-flex h-9 items-center rounded-[var(--radius-md)] bg-db-black px-[18px] text-[0.85rem] text-db-ink-0 no-underline hover:bg-db-ink-800"

type ExpertItemProps = {
  expert: LibraryPersona
  intl: string
  t: Translate
  onDelete: (id: string) => void
}

function ExpertCard({ expert, intl, t, onDelete }: ExpertItemProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{expert.name}</div>
            <span className="av">{personaInitials(expert.name)}</span>
          </div>
          <div className="meta-line">
            {t("experts.list.metaLine", {
              occ: expert.occ,
              when: formatLibraryDate(expert.updated, intl),
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
                onClick={() => onDelete(expert.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/bolag/experter/${expert.id}`}>
                {t("common.open")}
              </Link>
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

function ExpertListRow({ expert, intl, t, onDelete }: ExpertItemProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="admin-list-row admin-list-pops">
      <div>
        <div className="nm">{expert.name}</div>
        <div className="meta">
          {t("experts.list.metaLine", {
            occ: expert.occ,
            when: formatLibraryDate(expert.updated, intl),
          })}
        </div>
      </div>
      <div className="cell">{expert.occ}</div>
      <div className="admin-list-actions">
        {confirming ? (
          <>
            <button type="button" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </button>
            <button type="button" className="primary" onClick={() => onDelete(expert.id)}>
              {t("common.deleteConfirm")}
            </button>
          </>
        ) : (
          <>
            <Link className="primary" to={`/bolag/experter/${expert.id}`}>
              {t("common.open")}
            </Link>
            <button type="button" onClick={() => setConfirming(true)}>
              {t("common.delete")}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export function ExpertsPage() {
  const { t, intl } = useLocale()
  const [rows, setRows] = useState<LibraryPersona[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [view, setView] = useState<ListViewMode>("grid")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void listExpertPersonas()
      .then((items) => {
        if (!cancelled) {
          setRows(items)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("experts.list.loadError"))
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
    return rows.filter(
      (row) =>
        !q ||
        row.name.toLowerCase().includes(q) ||
        row.occ.toLowerCase().includes(q),
    )
  }, [rows, query])

  async function handleDelete(id: string) {
    try {
      await deletePersona(id)
      setRows((prev) => prev.filter((row) => row.id !== id))
      setToast(t("experts.list.deleted"))
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  return (
    <div className="wrap">
      <div className="head-row">
        <div>
          <h1>{t("experts.list.title")}</h1>
          <p>{t("experts.list.description")}</p>
        </div>
      </div>

      {error ? (
        <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="no-match">{t("experts.list.loading")}</div>
      ) : rows.length > 0 ? (
        <>
          <div className="controls-row">
            <div className="controls-left">
              <input
                className="dsearch"
                placeholder={t("experts.list.searchPlaceholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="controls-right">
              <ViewToggle value={view} onChange={setView} />
              <Link to="/bolag/experter/new" className={CTA_CLASS}>
                {t("experts.list.newExpert")}
              </Link>
            </div>
          </div>
          {list.length === 0 ? (
            <div className="no-match">{t("experts.list.emptyFilter", { query })}</div>
          ) : view === "grid" ? (
            <div className="pop-grid">
              {list.map((expert) => (
                <ExpertCard
                  key={expert.id}
                  expert={expert}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                />
              ))}
            </div>
          ) : (
            <div className="admin-list-stack">
              {list.map((expert) => (
                <ExpertListRow
                  key={expert.id}
                  expert={expert}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <h2 style={{ font: "var(--text-h2)", marginBottom: 10 }}>
            {t("experts.list.emptyTitle")}
          </h2>
          <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>
            {t("experts.list.emptyBody")}
          </p>
          <Link to="/bolag/experter/new" className={CTA_CLASS}>
            {t("experts.list.newExpert")}
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
