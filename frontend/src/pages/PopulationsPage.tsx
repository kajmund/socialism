import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  deletePopulation,
  duplicatePopulation,
  listPopulations,
} from "@/api/populations"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { FP_COLORS, formatLibraryDate } from "@/data/library"
import type { PopulationSummary } from "@/data/library-types"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

type PopCardProps = {
  pop: PopulationSummary
  intl: string
  t: Translate
  onDelete: (id: number) => void
  onDup: (id: number, name: string) => void
}

function PopCard({ pop, intl, t, onDelete, onDup }: PopCardProps) {
  const [confirming, setConfirming] = useState(false)
  const fpLabels = [
    t("populations.list.fpAge"),
    t("populations.list.fpLean"),
    t("populations.list.fpDistrict"),
  ] as const
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{pop.name}</div>
            {pop.versions > 1 && (
              <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
                {t("common.versions", { count: pop.versions })}
              </span>
            )}
          </div>
          <div className="meta-line">
            {t("populations.list.metaLine", {
              size: pop.size,
              when: formatLibraryDate(pop.updated, intl),
            })}
          </div>
          <div className="fingerprint">
            {fpLabels.map((label, i) => (
              <div className="fp-row" key={label}>
                <div className="fp-lbl">{label}</div>
                <div className="fp-bar">
                  {(pop.fp[i] ?? [0, 0, 0]).map((v, j) => (
                    <span
                      key={j}
                      style={{ width: v + "%", background: FP_COLORS[j] }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="usage-row">
            {pop.runs > 0 ? (
              <span>
                {t("populations.list.usedInPrefix")} <b>{pop.runs}</b>{" "}
                {t("populations.list.usedInSuffix")}
              </span>
            ) : (
              <span className="unused">{t("populations.list.unused")}</span>
            )}
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
                onClick={() => onDelete(pop.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/populations/${pop.id}`}>
                {t("common.open")}
              </Link>
              <button type="button" onClick={() => onDup(pop.id, pop.name)}>
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

export function PopulationsPage() {
  const { t, intl } = useLocale()
  const [pops, setPops] = useState<PopulationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [sort, setSort] = useState<"updated" | "size" | "runs">("updated")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listPopulations()
      .then((data) => {
        if (!cancelled) {
          setPops(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("populations.list.loadError"))
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
    let next = pops.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))
    if (sort === "updated") {
      next = [...next].sort(
        (a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime(),
      )
    }
    if (sort === "size") next = [...next].sort((a, b) => b.size - a.size)
    if (sort === "runs") next = [...next].sort((a, b) => b.runs - a.runs)
    return next
  }, [pops, query, sort])

  function showToast(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2400)
  }

  async function handleDelete(id: number) {
    try {
      await deletePopulation(id)
      setPops((prev) => prev.filter((x) => x.id !== id))
      showToast(t("populations.list.deleted"))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  async function handleDup(id: number, name: string) {
    try {
      const copy = await duplicatePopulation(id)
      setPops((prev) => [copy, ...prev])
      showToast(t("populations.list.duplicated", { name }))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.duplicateError"))
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
                margin: 0,
              }}
            >
              {t("populations.list.title")}
            </h1>
            <div
              style={{
                font: "var(--text-body-sm)",
                color: "var(--text-muted)",
                marginTop: 6,
                maxWidth: 640,
              }}
            >
              {t("populations.list.intro")}
            </div>
          </div>
        </div>

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        {loading ? (
          <div className="no-match">{t("populations.list.loading")}</div>
        ) : pops.length > 0 ? (
          <>
            <div className="controls-row">
              <div className="controls-left">
                <input
                  className="dsearch"
                  placeholder={t("populations.list.searchPlaceholder")}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <select
                  className="dsel"
                  value={sort}
                  onChange={(e) =>
                    setSort(e.target.value as "updated" | "size" | "runs")
                  }
                >
                  <option value="updated">{t("populations.list.sortUpdated")}</option>
                  <option value="size">{t("populations.list.sortSize")}</option>
                  <option value="runs">{t("populations.list.sortRuns")}</option>
                </select>
              </div>
              <Link
                to="/populations/new"
                className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
              >
                {t("populations.list.newPopulation")}
              </Link>
            </div>
            <div className="pop-grid">
              {list.length ? (
                list.map((p) => (
                  <PopCard
                    key={p.id}
                    pop={p}
                    intl={intl}
                    t={t}
                    onDelete={handleDelete}
                    onDup={handleDup}
                  />
                ))
              ) : (
                <div className="no-match">
                  {t("populations.list.emptyFilter", { query })}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="empty-state">
            <h2 style={{ font: "var(--text-h2)", marginBottom: 10 }}>
              {t("populations.list.emptyTitle")}
            </h2>
            <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>
              {t("populations.list.emptyBody")}
            </p>
            <Link
              to="/populations/new"
              className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline"
            >
              {t("populations.list.newPopulation")}
            </Link>
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
