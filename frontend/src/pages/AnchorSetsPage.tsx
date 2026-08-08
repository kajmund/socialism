import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  deleteAnchorSet,
  duplicateAnchorSet,
  listAnchorSets,
  publishAnchorSet,
  type AnchorKind,
  type AnchorLocale,
  type SsrAnchorSet,
} from "@/api/anchorSets"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = ReturnType<typeof useLocale>["t"]

function kindLabel(kind: AnchorKind, t: Translate): string {
  return kind === "tone" ? t("anchorSets.kindTone") : t("anchorSets.kindStyle")
}

function statusLabel(status: SsrAnchorSet["status"], t: Translate): string {
  return status === "published"
    ? t("anchorSets.statusPublished")
    : t("anchorSets.statusDraft")
}

export function AnchorSetsPage() {
  const { t } = useLocale()
  const [rows, setRows] = useState<SsrAnchorSet[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [kindFilter, setKindFilter] = useState<"" | AnchorKind>("")
  const [localeFilter, setLocaleFilter] = useState<"" | AnchorLocale>("")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listAnchorSets()
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("anchorSets.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const filtered = useMemo(() => {
    return rows.filter((row) => {
      if (kindFilter && row.kind !== kindFilter) return false
      if (localeFilter && row.locale !== localeFilter) return false
      return true
    })
  }, [rows, kindFilter, localeFilter])

  async function onPublish(id: number) {
    try {
      const updated = await publishAnchorSet(id)
      setRows((prev) => prev.map((r) => (r.id === id ? updated : r)))
      setToast(t("anchorSets.list.published"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  async function onDuplicate(id: number) {
    try {
      const copy = await duplicateAnchorSet(id)
      setRows((prev) => [copy, ...prev])
      setToast(t("anchorSets.list.duplicated"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  async function onDelete(id: number) {
    try {
      await deleteAnchorSet(id)
      setRows((prev) => prev.filter((r) => r.id !== id))
      setToast(t("anchorSets.list.deleted"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  return (
    <div>
      <div className="head-row">
        <div>
          <h1>{t("anchorSets.list.title")}</h1>
          <p className="muted">{t("anchorSets.list.intro")}</p>
        </div>
        <Link to="/tools/anchor-sets/new" className="primary">
          {t("anchorSets.list.new")}
        </Link>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <select
          className="dsel"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value as "" | AnchorKind)}
        >
          <option value="">{t("anchorSets.list.allKinds")}</option>
          <option value="tone">{t("anchorSets.kindTone")}</option>
          <option value="style">{t("anchorSets.kindStyle")}</option>
        </select>
        <select
          className="dsel"
          value={localeFilter}
          onChange={(e) => setLocaleFilter(e.target.value as "" | AnchorLocale)}
        >
          <option value="">{t("anchorSets.list.allLocales")}</option>
          <option value="sv">{t("configurations.language.sv")}</option>
          <option value="en">{t("configurations.language.en")}</option>
          <option value="nb">{t("configurations.language.nb")}</option>
        </select>
      </div>

      {loading && <p className="muted">{t("anchorSets.list.loading")}</p>}
      {error && <p className="text-destructive">{error}</p>}
      {toast && <p className="text-sm text-[color:var(--db-success)]">{toast}</p>}

      {!loading && filtered.length === 0 ? (
        <p className="muted">{t("anchorSets.list.empty")}</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((row) => (
            <div key={row.id} className="pop-card">
              <Card className="h-full gap-0 py-4 ring-1 ring-border">
                <CardContent className="pop-inner px-4 space-y-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{row.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {kindLabel(row.kind, t)} · {row.locale.toUpperCase()} · v
                        {row.version}
                      </div>
                    </div>
                    <span className="rounded-full border px-2 py-0.5 text-[11px]">
                      {statusLabel(row.status, t)}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t("anchorSets.list.labelCount", { count: row.labels.length })}
                  </div>
                  <div className="flex flex-wrap gap-2 pt-2">
                    <Link className="primary text-sm" to={`/tools/anchor-sets/${row.id}/edit`}>
                      {t("anchorSets.list.edit")}
                    </Link>
                    {row.status === "draft" ? (
                      <AdminButton
                        type="button"
                        variant="secondary"
                        onClick={() => void onPublish(row.id)}
                      >
                        {t("anchorSets.list.publish")}
                      </AdminButton>
                    ) : (
                      <AdminButton
                        type="button"
                        variant="secondary"
                        onClick={() => void onDuplicate(row.id)}
                      >
                        {t("anchorSets.list.duplicate")}
                      </AdminButton>
                    )}
                    {row.status === "draft" ? (
                      <AdminButton
                        type="button"
                        variant="secondary"
                        onClick={() => void onDelete(row.id)}
                      >
                        {t("common.delete")}
                      </AdminButton>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
