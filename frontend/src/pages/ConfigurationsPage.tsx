import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  activateConfiguration,
  deleteConfiguration,
  listConfigurations,
  type Configuration,
  type ConfigurationLanguage,
} from "@/api/configurations"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

function languageLabel(language: ConfigurationLanguage, t: Translate): string {
  switch (language) {
    case "sv":
      return t("configurations.language.sv")
    case "en":
      return t("configurations.language.en")
    case "nb":
      return t("configurations.language.nb")
    default: {
      const exhaustive: never = language
      return exhaustive
    }
  }
}

type ConfigCardProps = {
  config: Configuration
  onDelete: (id: number) => void
  onActivate: (id: number) => void
}

function ConfigCard({ config, onDelete, onActivate }: ConfigCardProps) {
  const { t } = useLocale()
  const [confirming, setConfirming] = useState(false)
  const promptCount = Object.keys(config.prompts).length
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{config.name}</div>
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {languageLabel(config.language, t)}
            </span>
          </div>
          <div className="meta-line">
            {config.is_active
              ? t("configurations.list.activeBadge")
              : t("configurations.list.inactiveBadge")}
            {" · "}
            {t("configurations.list.promptCount", { count: promptCount })}
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
                onClick={() => onDelete(config.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/configurations/${config.id}/edit`}>
                {t("configurations.list.edit")}
              </Link>
              {!config.is_active ? (
                <button type="button" onClick={() => onActivate(config.id)}>
                  {t("configurations.list.activate")}
                </button>
              ) : null}
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

export function ConfigurationsPage() {
  const { t } = useLocale()
  const [configs, setConfigs] = useState<Configuration[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [languageFilter, setLanguageFilter] = useState<"" | ConfigurationLanguage>("")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listConfigurations()
      .then((data) => {
        if (!cancelled) {
          setConfigs(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("configurations.list.loadError"))
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
    const timer = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return configs.filter((c) => {
      if (languageFilter && c.language !== languageFilter) return false
      if (!q) return true
      return c.name.toLowerCase().includes(q)
    })
  }, [configs, query, languageFilter])

  async function onDelete(id: number) {
    try {
      await deleteConfiguration(id)
      setConfigs((prev) => prev.filter((c) => c.id !== id))
      setToast(t("configurations.list.deleted"))
    } catch (err: unknown) {
      setToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  async function onActivate(id: number) {
    try {
      const updated = await activateConfiguration(id)
      setConfigs((prev) =>
        prev.map((c) => {
          if (c.id === updated.id) return updated
          return { ...c, is_active: false }
        }),
      )
      setToast(t("configurations.list.activated"))
    } catch (err: unknown) {
      setToast(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>{t("configurations.list.title")}</h1>
            <p className="muted">{t("configurations.list.intro")}</p>
          </div>
        </div>

        <div className="controls-row">
          <div className="controls-left">
            <input
              className="dsearch"
              placeholder={t("configurations.list.searchPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              className="dsel"
              value={languageFilter}
              onChange={(e) =>
                setLanguageFilter(e.target.value as "" | ConfigurationLanguage)
              }
            >
              <option value="">{t("configurations.list.allLanguages")}</option>
              <option value="sv">{t("configurations.language.sv")}</option>
              <option value="en">{t("configurations.language.en")}</option>
              <option value="nb">{t("configurations.language.nb")}</option>
            </select>
          </div>
          <Link
            to="/configurations/new"
            className="admin-cta inline-flex h-9 shrink-0 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
          >
            {t("configurations.list.new")}
          </Link>
        </div>

        {loading && <p className="muted">{t("configurations.list.loading")}</p>}
        {error && <p className="text-destructive">{error}</p>}
        {!loading && !error && filtered.length === 0 && (
          <div className="empty-state">
            <p>{t("configurations.list.empty")}</p>
            <Link
              to="/configurations/new"
              className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
            >
              {t("configurations.list.createFirst")}
            </Link>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((config) => (
            <ConfigCard
              key={config.id}
              config={config}
              onDelete={onDelete}
              onActivate={onActivate}
            />
          ))}
        </div>
      </div>
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
