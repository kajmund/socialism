import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { deletePersona, listExpertPersonas } from "@/api/personas"
import { BolagShell } from "@/components/layout/BolagShell"
import { AdminButton } from "@/components/ui/admin-button"
import { formatLibraryDate } from "@/data/library"
import type { LibraryPersona } from "@/data/library-types"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function ExpertsPage() {
  const { t, locale } = useLocale()
  const [rows, setRows] = useState<LibraryPersona[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState("")
  const [toast, setToast] = useState("")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void listExpertPersonas({ q: query.trim() || undefined })
      .then((items) => {
        if (!cancelled) setRows(items)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setToast(err instanceof ApiError ? err.message : t("experts.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [query, t])

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
              {t("experts.list.title")}
            </h1>
            <p
              style={{
                font: "var(--text-body-sm)",
                color: "var(--text-muted)",
                marginTop: 6,
                maxWidth: 640,
              }}
            >
              {t("experts.list.description")}
            </p>
          </div>
          <Link to="/bolag/experter/new" className="no-underline">
            <AdminButton variant="primary">{t("experts.list.newExpert")}</AdminButton>
          </Link>
        </div>

        <div className="controls-row" style={{ marginTop: 24 }}>
          <input
            className="dsearch"
            placeholder={t("experts.list.searchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        {loading ? (
          <p style={{ color: "var(--text-muted)", marginTop: 24 }}>{t("experts.list.loading")}</p>
        ) : rows.length === 0 ? (
          <p style={{ color: "var(--text-muted)", marginTop: 24 }}>{t("experts.list.empty")}</p>
        ) : (
          <div className="table-wrap" style={{ marginTop: 24 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("experts.list.columnName")}</th>
                  <th>{t("experts.list.columnBackground")}</th>
                  <th>{t("experts.list.columnUpdated")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link to={`/bolag/experter/${row.id}`} className="row-link">
                        {row.name}
                      </Link>
                    </td>
                    <td>{row.occ}</td>
                    <td>{formatLibraryDate(row.updated, locale)}</td>
                    <td>
                      <button
                        type="button"
                        className="linkish"
                        onClick={() => void handleDelete(row.id)}
                      >
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
