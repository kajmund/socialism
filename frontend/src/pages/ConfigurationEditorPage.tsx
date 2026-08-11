import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  CONFIGURATION_LANGUAGES,
  DEFAULT_SSR_TEMPERATURE,
  createConfiguration,
  getConfiguration,
  getPromptCatalog,
  updateConfiguration,
  type ConfigurationLanguage,
  type PromptCatalog,
  type PromptField,
} from "@/api/configurations"
import {
  DEFAULT_REPORT_THRESHOLDS,
  cloneReportThresholds,
  reportThresholdValidationKey,
  type ReportThresholds,
} from "@/api/reportThresholds"
import {
  listAnchorSets,
  type ConfigurationAnchorSets,
  type SsrAnchorSet,
} from "@/api/anchorSets"
import { CatalogEditor } from "@/components/config/CatalogEditor"
import { ReportThresholdsEditor } from "@/components/config/ReportThresholdsEditor"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

type EditorTopTab = "prompts" | "ssr" | "grunddata"

const EMPTY_ANCHOR_REFS: ConfigurationAnchorSets = {
  sv: { tone: 0, style: 0 },
  en: { tone: 0, style: 0 },
}

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

/** Catalog field labels follow the configuration language, not the GUI locale. */
function labelLocaleFor(language: ConfigurationLanguage): ConfigurationLanguage {
  return language === "en" ? "en" : "sv"
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
  const { t } = useLocale()
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id?: string }>()
  const isEdit = Boolean(editId)
  const numericId = editId ? Number(editId) : NaN

  const [name, setName] = useState("")
  const [language, setLanguage] = useState<ConfigurationLanguage>("sv")
  const [isActive, setIsActive] = useState(false)
  const [prompts, setPrompts] = useState<Record<string, string>>({})
  const [ssrTemperature, setSsrTemperature] = useState(DEFAULT_SSR_TEMPERATURE)
  const [reportThresholds, setReportThresholds] = useState<ReportThresholds>(() =>
    cloneReportThresholds(DEFAULT_REPORT_THRESHOLDS),
  )
  const [anchorSets, setAnchorSets] = useState<ConfigurationAnchorSets>(EMPTY_ANCHOR_REFS)
  const [libraryAnchors, setLibraryAnchors] = useState<SsrAnchorSet[]>([])
  const [catalog, setCatalog] = useState<PromptCatalog | null>(null)
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)
  const [topTab, setTopTab] = useState<EditorTopTab>("prompts")
  const [rowReady, setRowReady] = useState(!isEdit)
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Saved prompt texts for the edit row — kept across language changes.
  const savedPromptsRef = useRef<Record<string, string> | null>(null)

  useEffect(() => {
    if (!isEdit) {
      setRowReady(true)
      savedPromptsRef.current = null
      return
    }
    let cancelled = false
    setRowReady(false)
    ;(async () => {
      try {
        if (!Number.isFinite(numericId)) {
          setError(t("configurations.editor.loadError"))
          return
        }
        const row = await getConfiguration(numericId)
        if (cancelled) return
        savedPromptsRef.current = { ...row.prompts }
        setName(row.name)
        setLanguage(row.language)
        setIsActive(row.is_active)
        setSsrTemperature(row.ssr_temperature)
        setReportThresholds(cloneReportThresholds(row.report_thresholds))
        setAnchorSets(row.anchor_sets)
        setError(null)
        setRowReady(true)
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t("configurations.editor.loadError"),
          )
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId, t])

  useEffect(() => {
    let cancelled = false
    listAnchorSets({ status: "published" })
      .then((rows) => {
        if (!cancelled) setLibraryAnchors(rows)
      })
      .catch(() => {
        if (!cancelled) setLibraryAnchors([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!rowReady) return
    let cancelled = false
    setCatalogLoading(true)
    ;(async () => {
      try {
        const cat = await getPromptCatalog({
          language,
          label_locale: labelLocaleFor(language),
        })
        if (cancelled) return
        setCatalog(cat)
        if (isEdit && savedPromptsRef.current) {
          setPrompts({ ...cat.defaults, ...savedPromptsRef.current })
        } else {
          setPrompts({ ...cat.defaults })
        }
        setActiveSectionId((prev) => {
          if (prev && cat.sections.some((s) => s.id === prev)) return prev
          return cat.sections[0]?.id ?? null
        })
        setError(null)
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t("configurations.editor.loadError"),
          )
        }
      } finally {
        if (!cancelled) setCatalogLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [rowReady, language, isEdit, t])

  const sections = useMemo(
    () => (catalog ? fieldsBySection(catalog) : []),
    [catalog],
  )

  const activeSection =
    sections.find((s) => s.id === activeSectionId) ?? sections[0] ?? null

  const loading = !rowReady || catalogLoading

  const reportThresholdValidation = reportThresholdValidationKey(reportThresholds)

  function setPromptValue(key: string, value: string) {
    setPrompts((prev) => {
      const next = { ...prev, [key]: value }
      if (isEdit) {
        savedPromptsRef.current = {
          ...(savedPromptsRef.current ?? {}),
          [key]: value,
        }
      }
      return next
    })
  }

  async function saveConfiguration() {
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError(t("configurations.editor.nameRequired"))
      return
    }
    if (!(ssrTemperature > 0)) {
      setError(t("configurations.editor.ssrTemperatureInvalid"))
      return
    }
    const thresholdValidation = reportThresholdValidationKey(reportThresholds)
    if (thresholdValidation) {
      setError(t(thresholdValidation))
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
          ssr_temperature: ssrTemperature,
          report_thresholds: reportThresholds,
          anchor_sets: anchorSets,
          is_active: isActive,
        })
        navigate("/tools/configurations")
      } else {
        const created = await createConfiguration({
          name: trimmedName,
          language,
          prompts,
          ssr_temperature: ssrTemperature,
          report_thresholds: reportThresholds,
          anchor_sets: anchorSets,
          is_active: isActive,
        })
        navigate(`/tools/configurations/${created.id}/edit`)
      }
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSaving(false)
    }
  }

  function anchorOptions(kind: "tone" | "style", loc: "sv" | "en") {
    return libraryAnchors.filter((row) => row.kind === kind && row.locale === loc)
  }

  function setAnchorRef(loc: "sv" | "en", kind: "tone" | "style", id: number) {
    setAnchorSets((prev) => ({
      ...prev,
      [loc]: { ...prev[loc], [kind]: id },
    }))
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void saveConfiguration()
  }

  return (
    <>
        <div className="mb-4 text-sm text-muted-foreground">
          <Link to="/tools/configurations" className="no-underline hover:underline">
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
          <div className="mt-6 space-y-6">
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
                  onChange={(e) => setLanguage(e.target.value as ConfigurationLanguage)}
                >
                  {CONFIGURATION_LANGUAGES.map((code) => (
                    <option key={code} value={code}>
                      {languageLabel(code, t)}
                    </option>
                  ))}
                </select>
                <span className="block text-xs text-muted-foreground">
                  {t("configurations.editor.languageHint")}
                </span>
              </label>

              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                />
                {t("configurations.editor.activeLabel")}
              </label>

              <div className="flex flex-wrap gap-3">
                <AdminButton
                  type="button"
                  variant="primary"
                  disabled={saving}
                  onClick={() => void saveConfiguration()}
                >
                  {saving ? t("common.saving") : t("common.save")}
                </AdminButton>
                <AdminButton
                  type="button"
                  variant="secondary"
                  disabled={saving}
                  onClick={() => navigate("/tools/configurations")}
                >
                  {t("common.cancel")}
                </AdminButton>
              </div>
            </div>

            <div
              role="tablist"
              aria-label={t("configurations.editor.topTablistAria")}
              className="flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
            >
              {(
                [
                  ["prompts", "configurations.editor.tabPrompts"],
                  ["ssr", "configurations.editor.tabSsr"],
                  ["grunddata", "configurations.editor.tabGrunddata"],
                ] as const
              ).map(([id, labelKey]) => {
                const selected = topTab === id
                return (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    id={`config-top-tab-${id}`}
                    aria-selected={selected}
                    aria-controls={`config-top-panel-${id}`}
                    tabIndex={selected ? 0 : -1}
                    className={
                      selected
                        ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium text-[color:var(--text-body)]"
                        : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                    }
                    onClick={() => setTopTab(id)}
                  >
                    {t(labelKey)}
                  </button>
                )
              })}
            </div>

            {topTab === "prompts" ? (
              <form
                id="config-top-panel-prompts"
                role="tabpanel"
                aria-labelledby="config-top-tab-prompts"
                className="space-y-6"
                onSubmit={onSubmit}
              >
                {sections.length > 0 && activeSection ? (
                  <div>
                    <div
                      role="tablist"
                      aria-label={t("configurations.editor.tablistAria")}
                      className="mb-3 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
                    >
                      {sections.map((section) => {
                        const selected = section.id === activeSection.id
                        return (
                          <button
                            key={section.id}
                            type="button"
                            role="tab"
                            id={`prompt-tab-${section.id}`}
                            aria-selected={selected}
                            aria-controls={`prompt-panel-${section.id}`}
                            tabIndex={selected ? 0 : -1}
                            className={
                              selected
                                ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium text-[color:var(--text-body)]"
                                : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                            }
                            onClick={() => setActiveSectionId(section.id)}
                          >
                            {section.label}
                          </button>
                        )
                      })}
                    </div>

                    <div
                      role="tabpanel"
                      id={`prompt-panel-${activeSection.id}`}
                      aria-labelledby={`prompt-tab-${activeSection.id}`}
                      className="space-y-5"
                    >
                      {activeSection.fields.map((field) => (
                        <label key={field.key} className="block space-y-1.5">
                          <span className="text-sm font-medium">{field.label}</span>
                          {field.hint ? (
                            <span className="block text-xs text-muted-foreground">
                              {field.hint}
                            </span>
                          ) : null}
                          <textarea
                            className="min-h-28 w-full rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
                            value={prompts[field.key] ?? ""}
                            onChange={(e) => setPromptValue(field.key, e.target.value)}
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                ) : null}
              </form>
            ) : topTab === "ssr" ? (
              <div
                id="config-top-panel-ssr"
                role="tabpanel"
                aria-labelledby="config-top-tab-ssr"
                className="max-w-2xl space-y-6"
              >
                <label className="block space-y-1.5">
                  <span className="text-sm font-medium">
                    {t("configurations.editor.ssrTemperatureLabel")}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {t("configurations.editor.ssrTemperatureHint")}
                  </span>
                  <input
                    type="number"
                    min={0.001}
                    max={10}
                    step={0.001}
                    className="w-36 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
                    value={ssrTemperature}
                    onChange={(e) => setSsrTemperature(Number(e.target.value))}
                  />
                </label>

                {(["sv", "en"] as const).map((loc) => (
                  <fieldset key={loc} className="space-y-3 rounded border p-4">
                    <legend className="px-1 text-sm font-medium">
                      {languageLabel(loc, t)}
                    </legend>
                    <label className="block space-y-1">
                      <span className="text-sm">{t("anchorSets.kindTone")}</span>
                      <select
                        className="dsel w-full"
                        value={anchorSets[loc].tone || ""}
                        onChange={(e) => setAnchorRef(loc, "tone", Number(e.target.value))}
                      >
                        <option value="">{t("configurations.editor.anchorPlaceholder")}</option>
                        {anchorOptions("tone", loc).map((row) => (
                          <option key={row.id} value={row.id}>
                            {row.name} (v{row.version})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block space-y-1">
                      <span className="text-sm">{t("anchorSets.kindStyle")}</span>
                      <select
                        className="dsel w-full"
                        value={anchorSets[loc].style || ""}
                        onChange={(e) => setAnchorRef(loc, "style", Number(e.target.value))}
                      >
                        <option value="">{t("configurations.editor.anchorPlaceholder")}</option>
                        {anchorOptions("style", loc).map((row) => (
                          <option key={row.id} value={row.id}>
                            {row.name} (v{row.version})
                          </option>
                        ))}
                      </select>
                    </label>
                  </fieldset>
                ))}

                <p className="text-xs text-muted-foreground">
                  {t("configurations.editor.anchorHint")}{" "}
                  <Link to="/tools/anchor-sets" className="underline">
                    {t("anchorSets.list.title")}
                  </Link>
                </p>

                <ReportThresholdsEditor
                  value={reportThresholds}
                  onChange={setReportThresholds}
                  validationKey={reportThresholdValidation}
                />
              </div>
            ) : (
              <div
                id="config-top-panel-grunddata"
                role="tabpanel"
                aria-labelledby="config-top-tab-grunddata"
              >
                {isEdit && Number.isFinite(numericId) ? (
                  <CatalogEditor configurationId={numericId} />
                ) : (
                  <p className="muted">{t("configurations.editor.grunddataSaveFirst")}</p>
                )}
              </div>
            )}
          </div>
        )}
    </>
  )
}
