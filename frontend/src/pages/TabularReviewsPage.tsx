import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { deleteTabularReview, listTabularReviews, type TabularReviewSummary } from "@/api/tabularReviews"
import { AdminShell } from "@/components/layout/AdminShell"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function TabularReviewsPage() {
  const { t, intl } = useLocale()
  const navigate = useNavigate()
  const [rows, setRows] = useState<TabularReviewSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listTabularReviews()
      .then((items) => {
        if (!cancelled) setRows(items)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("tabularReview.list.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  async function onDelete(id: number) {
    try {
      await deleteTabularReview(id)
      setRows((prev) => prev.filter((row) => row.id !== id))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  return (
    <AdminShell>
      <div className="wrap admin-page">
        <div className="admin-page-chrome">
          <div className="head-row">
            <div>
              <h1>{t("tabularReview.list.title")}</h1>
              <p className="muted">{t("tabularReview.list.intro")}</p>
            </div>
            <AdminButton type="button" variant="primary" onClick={() => navigate("/tabular-review/new")}>
              {t("tabularReview.list.new")}
            </AdminButton>
          </div>
        </div>
        <div className="admin-page-body space-y-3">
          {loading ? <p className="muted">{t("tabularReview.list.loading")}</p> : null}
          {error ? <p className="text-destructive">{error}</p> : null}
          {!loading && rows.length === 0 ? <p className="muted">{t("tabularReview.list.empty")}</p> : null}
          {rows.map((row) => (
            <Card key={row.id}>
              <CardContent className="flex items-center justify-between gap-3 py-3">
                <div>
                  <Link className="font-medium" to={`/tabular-review/${row.id}`}>
                    {row.name}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {t("tabularReview.list.meta", {
                      documents: row.document_count,
                      columns: row.column_count,
                      updated: new Intl.DateTimeFormat(intl, { dateStyle: "short" }).format(
                        new Date(row.updated_at),
                      ),
                    })}
                  </p>
                </div>
                <AdminButton type="button" onClick={() => void onDelete(row.id)}>
                  {t("common.delete")}
                </AdminButton>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </AdminShell>
  )
}
