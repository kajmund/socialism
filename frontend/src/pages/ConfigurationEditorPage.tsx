import { useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  CONFIGURATION_LANGUAGES,
  createConfiguration,
  getConfiguration,
  updateConfiguration,
  type ConfigurationLanguage,
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

export function ConfigurationEditorPage() {
  const { t } = useLocale()
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id?: string }>()
  const isEdit = Boolean(editId)
  const numericId = editId ? Number(editId) : NaN

  const [name, setName] = useState("")
  const [language, setLanguage] = useState<ConfigurationLanguage>("sv")
  const [promptText, setPromptText] = useState("")
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isEdit) return
    if (!Number.isFinite(numericId)) {
      setError(t("configurations.editor.loadError"))
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    getConfiguration(numericId)
      .then((row) => {
        if (cancelled) return
        setName(row.name)
        setLanguage(row.language)
        setPromptText(row.prompt_text)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t("configurations.editor.loadError"),
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId, t])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmedName = name.trim()
    const trimmedPrompt = promptText.trim()
    if (!trimmedName) {
      setError(t("configurations.editor.nameRequired"))
      return
    }
    if (!trimmedPrompt) {
      setError(t("configurations.editor.promptRequired"))
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (isEdit) {
        await updateConfiguration(numericId, {
          name: trimmedName,
          language,
          prompt_text: trimmedPrompt,
        })
      } else {
        await createConfiguration({
          name: trimmedName,
          language,
          prompt_text: trimmedPrompt,
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

        {!loading && (
          <form className="mt-6 max-w-2xl space-y-5" onSubmit={onSubmit}>
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
                onChange={(e) => setLanguage(e.target.value as ConfigurationLanguage)}
              >
                {CONFIGURATION_LANGUAGES.map((code) => (
                  <option key={code} value={code}>
                    {languageLabel(code, t)}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm font-medium">
                {t("configurations.editor.promptLabel")}
              </span>
              <textarea
                className="min-h-48 w-full rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 text-sm"
                value={promptText}
                onChange={(e) => setPromptText(e.target.value)}
                placeholder={t("configurations.editor.promptPlaceholder")}
              />
            </label>

            <div className="flex flex-wrap gap-3">
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
