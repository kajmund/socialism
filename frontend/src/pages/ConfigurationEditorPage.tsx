import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  CONFIGURATION_LANGUAGES,
  createConfiguration,
  getConfiguration,
  getPromptCatalog,
  updateConfiguration,
  type ConfigurationLanguage,
  type PromptCatalog,
  type PromptField,
} from "@/api/configurations"
import { AdminShell } from "@/components/layout/AdminShell"
import { AdminButton } from "@/components/ui/admin-button"
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

function fieldsBySection(
  catalog: PromptCatalog,
): { id: string; label: string; fields: PromptField[] }[] {
  return catalog.sections.map((section) => ({
    id: section.id,
    label: section.label,
    fields: catalog.fields.filter((f) => f.section === section.id),
  }))
}

export function ConfigurationEditorPage() {
  const { t, locale } = useLocale()
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id?: string }>()
  const isEdit = Boolean(editId)
  const numericId = editId ? Number(editId) : NaN
  const labelLocale: ConfigurationLanguage = locale === "en" ? "en" : "sv"

  const [name, setName] = useState("")
  const [language, setLanguage] = useState<ConfigurationLanguage>("sv")
  const [isActive, setIsActive] = useState(false)
  const [prompts, setPrompts] = useState<Record<string, string>>({})
  const [catalog, setCatalog] = useState<PromptCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // When editing, ignore language state changes after the row loads.
  const catalogLanguage = isEdit ? null : language

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        if (isEdit) {
          if (!Number.isFinite(numericId)) {
            setError(t("configurations.editor.loadError"))
            return
          }
          const row = await getConfiguration(numericId)
          if (cancelled) return
          const cat = await getPromptCatalog({
            language: row.language,
            label_locale: labelLocale,
          })
          if (cancelled) return
          setCatalog(cat)
          setName(row.name)
          setLanguage(row.language)
          setIsActive(row.is_active)
          setPrompts({ ...cat.defaults, ...row.prompts })
        } else {
          const cat = await getPromptCatalog({
            language: catalogLanguage ?? "sv",
            label_locale: labelLocale,
          })
          if (cancelled) return
          setCatalog(cat)
          setPrompts({ ...cat.defaults })
        }
        setError(null)
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t("configurations.editor.loadError"),
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId, catalogLanguage, labelLocale, t])

  const sections = useMemo(
    () => (catalog ? fieldsBySection(catalog) : []),
    [catalog],
  )

  function setPromptValue(key: string, value: string) {
    setPrompts((prev) => ({ ...prev, [key]: value }))
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError(t("configurations.editor.nameRequired"))
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (isEdit) {
        await updateConfiguration(numericId, {
          name: trimmedName,
          language,
          prompts,
          is_active: isActive,
        })
      } else {
        await createConfiguration({
          name: trimmedName,
          language,
          prompts,
          is_active: isActive,
        })
      }
      navigate("/configurations")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSaving(false)
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="mb-4 text-sm text-muted-foreground">
          <Link to="/configurations" className="no-underline hover:underline">
            {t("configurations.list.title")}
          </Link>
          <span className="mx-2">/</span>
          <span>
            {isEdit ? t("configurations.editor.editTitle") : t("configurations.editor.newTitle")}
          </span>
        </div>

        <div className="head-row">
          <div>
            <h1>
              {isEdit ? t("configurations.editor.editTitle") : t("configurations.editor.newTitle")}
            </h1>
            <p className="muted">
              {isEdit
                ? t("configurations.editor.editIntro")
                : t("configurations.editor.newIntro")}
            </p>
          </div>
        </div>

        {loading && <p className="muted">{t("configurations.editor.loading")}</p>}
        {error && <p className="text-destructive">{error}</p>}

        {!loading && catalog && (
          <form className="mt-6 space-y-8" onSubmit={onSubmit}>
            <div className="grid max-w-2xl gap-5">
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">{t("configurations.editor.nameLabel")}</span>
                <input
                  className="dsearch w-full"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("configurations.editor.namePlaceholder")}
                  autoComplete="off"
                />
              </label>

              <label className="block space-y-1.5">
                <span className="text-sm font-medium">
                  {t("configurations.editor.languageLabel")}
                </span>
                <select
                  className="dsel w-full max-w-xs"
                  value={language}
                  disabled={isEdit}
                  onChange={(e) => setLanguage(e.target.value as ConfigurationLanguage)}
                >
                  {CONFIGURATION_LANGUAGES.map((code) => (
                    <option key={code} value={code}>
                      {languageLabel(code, t)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                />
                {t("configurations.editor.activeLabel")}
              </label>
            </div>

            {sections.map((section) => (
              <section key={section.id} className="space-y-4 border-t border-[color:var(--border-hairline)] pt-6">
                <h2 className="text-lg font-medium">{section.label}</h2>
                <div className="space-y-5">
                  {section.fields.map((field) => (
                    <label key={field.key} className="block space-y-1.5">
                      <span className="text-sm font-medium">{field.label}</span>
                      {field.hint ? (
                        <span className="block text-xs text-muted-foreground">{field.hint}</span>
                      ) : null}
                      <textarea
                        className="min-h-28 w-full rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
                        value={prompts[field.key] ?? ""}
                        onChange={(e) => setPromptValue(field.key, e.target.value)}
                      />
                    </label>
                  ))}
                </div>
              </section>
            ))}

            <div className="flex flex-wrap gap-3 border-t border-[color:var(--border-hairline)] pt-6">
              <AdminButton type="submit" variant="primary" disabled={saving}>
                {saving ? t("common.saving") : t("common.save")}
              </AdminButton>
              <AdminButton
                type="button"
                variant="secondary"
                disabled={saving}
                onClick={() => navigate("/configurations")}
              >
                {t("common.cancel")}
              </AdminButton>
            </div>
          </form>
        )}
      </div>
    </AdminShell>
  )
}
