import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  deletePopulation,
  duplicatePopulation,
  listPopulations,
} from "@/api/populations"
import type { PopulationSummary } from "@/data/library-types"
import { BolagShell } from "@/components/layout/BolagShell"
import { AdminButton } from "@/components/ui/admin-button"
import { formatLibraryDate } from "@/data/library"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function ExpertPanelsPage() {
  const { t, locale } = useLocale()
  const [panels, setPanels] = useState<PopulationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState("")
  const [toast, setToast] = useState("")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void listPopulations({ kind: "expert_panel" })
      .then((rows) => {
        if (!cancelled) setPanels(rows)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setToast(err instanceof ApiError ? err.message : t("expertPanels.list.loadError"))
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
    <BolagShell>
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
              {t("expertPanels.list.title")}
            </h1>
            <p
              style={{
                font: "var(--text-body-sm)",
                color: "var(--text-muted)",
                marginTop: 6,
                maxWidth: 640,
              }}
            >
              {t("expertPanels.list.intro")}
            </p>
          </div>
          <Link to="/bolag/expertpaneler/new" className="no-underline">
            <AdminButton variant="primary">{t("expertPanels.list.newPanel")}</AdminButton>
          </Link>
        </div>

        <div className="controls-row" style={{ marginTop: 24 }}>
          <input
            className="dsearch"
            placeholder={t("expertPanels.list.searchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        {loading ? (
          <p style={{ color: "var(--text-muted)", marginTop: 24 }}>{t("expertPanels.list.loading")}</p>
        ) : list.length === 0 ? (
          <p style={{ color: "var(--text-muted)", marginTop: 24 }}>{t("expertPanels.list.empty")}</p>
        ) : (
          <div className="table-wrap" style={{ marginTop: 24 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("expertPanels.list.columnName")}</th>
                  <th>{t("expertPanels.list.columnSize")}</th>
                  <th>{t("expertPanels.list.columnUpdated")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link to={`/bolag/expertpaneler/${row.id}`} className="row-link">
                        {row.name}
                      </Link>
                    </td>
                    <td>{row.size}</td>
                    <td>{formatLibraryDate(row.updated, locale)}</td>
                    <td className="actions-cell">
                      <button type="button" className="linkish" onClick={() => void handleDuplicate(row.id)}>
                        {t("common.duplicate")}
                      </button>
                      <button type="button" className="linkish" onClick={() => void handleDelete(row.id)}>
                        {t("common.delete")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {toast ? (
          <div className="toast" role="status">
            <div className="ck">✓</div>
            {toast}
          </div>
        ) : null}
      </div>
    </BolagShell>
  )
}
