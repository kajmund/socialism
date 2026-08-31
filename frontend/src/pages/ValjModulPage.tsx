import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { listModules, type ProductModule } from "@/api/modules"
import { useAuth } from "@/auth/AuthProvider"
import { AdminShell } from "@/components/layout/AdminShell"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { MODULE_HOME_PATHS } from "@/lib/moduleHomePaths"
import { MODULE_REGISTRY } from "@/modules/moduleRegistry"

export function ValjModulPage() {
  const { t } = useLocale()
  const { resolvedModules } = useAuth()
  const [modules, setModules] = useState<ProductModule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listModules()
      .then((rows) => {
        if (cancelled) return
        setModules(rows)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("valjModul.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const items = useMemo(() => {
    return resolvedModules.flatMap((id) => {
      const href = MODULE_HOME_PATHS[id]
      if (!href) return []
      const catalog = modules.find((row) => row.id === id)
      const manifest = MODULE_REGISTRY[id]
      const name = manifest ? t(manifest.nameKey) : (catalog?.name ?? id)
      const icon = catalog?.icon ?? manifest?.icon ?? ""
      return [{ id, href, name, icon }]
    })
  }, [modules, resolvedModules, t])

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row mb-2">
          <div>
            <h1>{t("valjModul.title")}</h1>
            <p className="muted">{t("valjModul.intro")}</p>
          </div>
        </div>
        {loading ? <p className="muted">{t("valjModul.loading")}</p> : null}
        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        {!loading && items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("valjModul.empty")}</p>
        ) : null}
        {!loading && items.length > 0 ? (
          <ul className="flex max-w-xl flex-col gap-2">
            {items.map((item) => (
              <li key={item.id}>
                <Link
                  to={item.href}
                  className="flex items-center gap-3 rounded-md border border-[color:var(--border-hairline)] px-4 py-3 no-underline text-[color:var(--text-body)] hover:border-db-ink-950"
                  aria-label={t("valjModul.openAria", { name: item.name })}
                >
                  {item.icon ? (
                    <span aria-hidden="true" className="text-lg">
                      {item.icon}
                    </span>
                  ) : null}
                  <span>{item.name}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </AdminShell>
  )
}
