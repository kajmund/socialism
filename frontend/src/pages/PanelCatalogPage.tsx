import { useEffect, useMemo, useState } from "react"
import { listModules, type ProductModule } from "@/api/modules"
import { PanelExpertProfilesEditor } from "@/components/tools/PanelExpertProfilesEditor"
import { PanelSubQuestionsEditor } from "@/components/tools/PanelSubQuestionsEditor"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { MODULE_REGISTRY } from "@/modules/moduleRegistry"

export function PanelCatalogPage() {
  const { t } = useLocale()
  const [modules, setModules] = useState<ProductModule[]>([])
  const [moduleId, setModuleId] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listModules()
      .then((rows) => {
        if (cancelled) return
        const withPanel = rows.filter((row) => row.components.includes("panel_engine"))
        setModules(withPanel)
        setModuleId((prev) => prev || withPanel[0]?.id || "")
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("tools.panelCatalog.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const selected = useMemo(
    () => modules.find((row) => row.id === moduleId) ?? null,
    [modules, moduleId],
  )

  function moduleLabel(id: string): string {
    const manifest = MODULE_REGISTRY[id]
    if (manifest) return t(manifest.nameKey)
    return modules.find((row) => row.id === id)?.name ?? id
  }

  if (loading) return <p className="muted">{t("tools.panelCatalog.loading")}</p>
  if (error) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {error}
      </p>
    )
  }
  if (modules.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("tools.panelCatalog.noModules")}</p>
  }

  return (
    <div className="space-y-8">
      <p className="muted">{t("tools.panelCatalog.intro")}</p>
      <label className="block text-sm">
        <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.moduleLabel")}</span>
        <select
          className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
          value={moduleId}
          aria-label={t("tools.panelCatalog.moduleLabel")}
          onChange={(event) => setModuleId(event.target.value)}
        >
          {modules.map((row) => (
            <option key={row.id} value={row.id}>
              {moduleLabel(row.id)}
            </option>
          ))}
        </select>
      </label>
      {selected ? (
        <>
          <PanelSubQuestionsEditor moduleId={selected.id} />
          <PanelExpertProfilesEditor moduleId={selected.id} />
        </>
      ) : null}
    </div>
  )
}
