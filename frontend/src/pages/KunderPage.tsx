import { useEffect, useMemo, useState } from "react"
import { listModules, type ProductModule } from "@/api/modules"
import { listKunder, updateKundModules, type Kund } from "@/api/kunder"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { MODULE_REGISTRY } from "@/modules/moduleRegistry"

export function KunderPage() {
  const { t } = useLocale()
  const [kunder, setKunder] = useState<Kund[]>([])
  const [modules, setModules] = useState<ProductModule[]>([])
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([listKunder(), listModules()])
      .then(([kundRows, moduleRows]) => {
        if (cancelled) return
        setKunder(kundRows)
        setModules(moduleRows)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("tools.kunder.loadError"))
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

  const knownIds = useMemo(() => modules.map((row) => row.id), [modules])

  function moduleLabel(id: string): string {
    const manifest = MODULE_REGISTRY[id]
    if (manifest) return t(manifest.nameKey)
    return modules.find((row) => row.id === id)?.name ?? id
  }

  async function toggleModule(kund: Kund, moduleId: string, enabled: boolean) {
    const next = enabled
      ? [...kund.available_modules.filter((id) => id !== moduleId), moduleId]
      : kund.available_modules.filter((id) => id !== moduleId)
    setSavingId(kund.id)
    setError(null)
    try {
      const updated = await updateKundModules(kund.id, next)
      setKunder((prev) => prev.map((row) => (row.id === updated.id ? updated : row)))
      setToast(t("tools.kunder.saved"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div className="space-y-4">
      <p className="muted">{t("tools.kunder.intro")}</p>
      {toast ? <p className="text-sm text-muted-foreground">{toast}</p> : null}
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p className="muted">{t("tools.kunder.loading")}</p> : null}
      {!loading && kunder.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("tools.kunder.empty")}</p>
      ) : null}
      {!loading && kunder.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[color:var(--border-hairline)]">
                <th className="px-2 py-1.5 font-medium">{t("tools.kunder.colName")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.kunder.colSlug")}</th>
                {knownIds.map((id) => (
                  <th key={id} className="px-2 py-1.5 font-medium">
                    {moduleLabel(id)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {kunder.map((kund) => (
                <tr key={kund.id} className="border-b border-[color:var(--border-hairline)]">
                  <td className="px-2 py-2">{kund.name}</td>
                  <td className="px-2 py-2 font-mono text-xs">{kund.slug}</td>
                  {knownIds.map((id) => {
                    const checked = kund.available_modules.includes(id)
                    return (
                      <td key={id} className="px-2 py-2">
                        <label className="inline-flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={savingId === kund.id}
                            aria-label={t("tools.kunder.toggleAria", {
                              kund: kund.name,
                              module: moduleLabel(id),
                            })}
                            onChange={(event) => {
                              void toggleModule(kund, id, event.target.checked)
                            }}
                          />
                        </label>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {savingId != null ? (
        <p className="text-sm text-muted-foreground">{t("common.saving")}</p>
      ) : null}
    </div>
  )
}
