import { useCallback, useEffect, useState } from "react"
import {
  clearEmbeddingCache,
  listEmbeddingCache,
  type EmbeddingCacheList,
} from "@/api/embeddings"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function EmbeddingCachePage() {
  const { t, intl } = useLocale()
  const [data, setData] = useState<EmbeddingCacheList | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await listEmbeddingCache())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.cache.loadError"))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void load()
  }, [load])

  async function onClear() {
    setBusy(true)
    setError(null)
    try {
      await clearEmbeddingCache()
      setConfirmClear(false)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.cache.clearError"))
    } finally {
      setBusy(false)
    }
  }

  function formatWhen(iso: string): string {
    if (!iso) return t("common.emDash")
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return new Intl.DateTimeFormat(intl, {
      dateStyle: "short",
      timeStyle: "short",
    }).format(d)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium">{t("tools.cache.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("tools.cache.intro")}</p>
          {data ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {t("tools.cache.meta", {
                count: data.count,
                model: data.embedding_model,
              })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={loading || busy} onClick={() => void load()}>
            {t("tools.cache.refresh")}
          </Button>
          {!confirmClear ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={busy || !data || data.count === 0}
              onClick={() => setConfirmClear(true)}
            >
              {t("tools.cache.clear")}
            </Button>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setConfirmClear(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={() => void onClear()}>
                {busy ? t("tools.cache.clearing") : t("tools.cache.clearConfirm")}
              </Button>
            </div>
          )}
        </div>
      </div>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p className="muted">{t("tools.cache.loading")}</p> : null}

      {!loading && data && data.entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("tools.cache.empty")}</p>
      ) : null}

      {!loading && data && data.entries.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[color:var(--border-hairline)]">
                <th className="px-2 py-1.5 font-medium">{t("tools.cache.colText")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.cache.colModel")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.cache.colDims")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.cache.colUpdated")}</th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((row) => (
                <tr key={row.id} className="border-b border-[color:var(--border-hairline)] align-top">
                  <td className="max-w-xl px-2 py-1.5 whitespace-pre-wrap break-words">{row.text}</td>
                  <td className="px-2 py-1.5 font-mono text-xs">{row.model}</td>
                  <td className="px-2 py-1.5 font-mono">{row.dims}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{formatWhen(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
