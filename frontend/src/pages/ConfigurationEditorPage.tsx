import { useEffect, useRef, useState } from "react"
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
} from "@/api/configurations"
import {
  DEFAULT_REPORT_THRESHOLDS,
  cloneReportThresholds,
  mergeReportThresholds,
  reportThresholdValidationKey,
  type ReportThresholds,
} from "@/api/reportThresholds"
import {
  listAnchorSets,
  type ConfigurationAnchorSets,
  type SsrAnchorSet,
} from "@/api/anchorSets"
import { CatalogEditor } from "@/components/config/CatalogEditor"
import { PromptFieldsPanel } from "@/components/config/PromptFieldsPanel"
import { ReportThresholdsEditor } from "@/components/config/ReportThresholdsEditor"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

type Translate = (key: MessageKey, params?: TranslateParams) => string

type EditorTopTab = "prompts" | "sensitivity" | "anchors" | "grunddata"

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

function languageShort(language: ConfigurationLanguage, t: Translate): string {
  switch (language) {
    case "sv":
      return t("configurations.editor.langSv")
    case "en":
      return t("configurations.editor.langEn")
    case "nb":
      return t("configurations.editor.langNb")
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
  const [topTab, setTopTab] = useState<EditorTopTab>("prompts")
  const [rowReady, setRowReady] = useState(!isEdit)
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
        setReportThresholds(mergeReportThresholds(row.report_thresholds))
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

  return (
    <>
      <div className="mb-2.5 text-sm text-muted-foreground">
        <Link to="/tools/configurations" className="no-underline hover:underline">
          {t("configurations.list.title")}
        </Link>
        <span className="mx-2">/</span>
        <span>
          {isEdit ? t("configurations.editor.editTitle") : t("configurations.editor.newTitle")}
        </span>
      </div>

      {loading && <p className="muted">{t("configurations.editor.loading")}</p>}
      {error && <p className="text-destructive">{error}</p>}

      {!loading && catalog && (
        <div className="mt-5 space-y-6">
          <div className="mb-5 flex flex-wrap items-center gap-3.5 rounded-[var(--radius-md)] bg-db-ink-100 px-3.5 py-2.5">
            <input
              className="min-w-40 flex-1 border-0 border-b-[1.5px] border-transparent bg-transparent px-0.5 py-1 text-[0.9rem] font-semibold text-[color:var(--text-body)] outline-none focus:border-db-ink-950"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("configurations.editor.namePlaceholder")}
              autoComplete="off"
              aria-label={t("configurations.editor.nameLabel")}
            />
            <div
              className="inline-flex shrink-0 gap-px rounded-lg border border-[color:var(--border-hairline)] bg-white p-0.5"
              role="group"
              aria-label={t("configurations.editor.languageAria")}
            >
              {CONFIGURATION_LANGUAGES.map((code) => {
                const selected = language === code
                return (
                  <button
                    key={code}
                    type="button"
                    className={cn(
                      "cursor-pointer rounded-md border-0 px-2.5 py-[5px] text-[0.7rem]",
                      selected
                        ? "bg-db-ink-950 text-white"
                        : "bg-transparent text-[color:var(--text-body)]",
                    )}
                    onClick={() => setLanguage(code)}
                  >
                    {languageShort(code, t)}
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={isActive}
              aria-label={t("configurations.editor.activeLabel")}
              className="flex shrink-0 items-center gap-[7px] border-0 bg-transparent p-0"
              onClick={() => setIsActive((prev) => !prev)}
            >
              <span
                className={cn(
                  "relative h-[17px] w-[30px] shrink-0 rounded-full",
                  isActive ? "bg-db-ink-950" : "bg-db-ink-200",
                )}
              >
                <span
                  className={cn(
                    "absolute top-0.5 h-[13px] w-[13px] rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,.2)]",
                    isActive ? "left-[15px]" : "left-0.5",
                  )}
                />
              </span>
              <span className="whitespace-nowrap text-xs text-[color:var(--text-body)]">
                {isActive
                  ? t("configurations.editor.activeOn")
                  : t("configurations.editor.activeOff")}
              </span>
            </button>
            <div className="ml-auto flex shrink-0 gap-1.5">
              <button
                type="button"
                disabled={saving}
                className="cursor-pointer rounded-md border-0 bg-db-black px-3.5 py-1.5 text-xs text-white disabled:opacity-40"
                onClick={() => void saveConfiguration()}
              >
                {saving ? t("common.saving") : t("common.save")}
              </button>
              <button
                type="button"
                disabled={saving}
                className="cursor-pointer rounded-md border border-[color:var(--border-hairline)] bg-white px-3.5 py-1.5 text-xs text-[color:var(--text-body)] disabled:opacity-40"
                onClick={() => navigate("/tools/configurations")}
              >
                {t("common.cancel")}
              </button>
            </div>
          </div>

          <div
            role="tablist"
            aria-label={t("configurations.editor.topTablistAria")}
            className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
          >
            {(
              [
                ["prompts", "configurations.editor.tabPrompts"],
                ["sensitivity", "configurations.editor.tabSensitivity"],
                ["anchors", "configurations.editor.tabAnchors"],
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
                  className={cn(
                    "-mb-px border-b-2 px-3 py-2 text-sm",
                    selected
                      ? "border-db-ink-950 font-semibold text-[color:var(--text-body)]"
                      : "border-transparent font-normal text-muted-foreground hover:text-[color:var(--text-body)]",
                  )}
                  onClick={() => setTopTab(id)}
                >
                  {t(labelKey)}
                </button>
              )
            })}
          </div>

          {topTab === "prompts" ? (
            <div
              id="config-top-panel-prompts"
              role="tabpanel"
              aria-labelledby="config-top-tab-prompts"
            >
              <PromptFieldsPanel catalog={catalog} prompts={prompts} onChange={setPromptValue} />
            </div>
          ) : null}

          {topTab === "sensitivity" ? (
            <div
              id="config-top-panel-sensitivity"
              role="tabpanel"
              aria-labelledby="config-top-tab-sensitivity"
            >
              <ReportThresholdsEditor
                value={reportThresholds}
                onChange={setReportThresholds}
                validationKey={reportThresholdValidation}
                ssrTemperature={ssrTemperature}
                onSsrTemperatureChange={setSsrTemperature}
              />
            </div>
          ) : null}

          {topTab === "anchors" ? (
            <div
              id="config-top-panel-anchors"
              role="tabpanel"
              aria-labelledby="config-top-tab-anchors"
              className="max-w-[760px]"
            >
              <p className="mb-5 text-[12.5px] text-muted-foreground">
                {t("configurations.editor.anchorsIntro")}
              </p>
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                {(["sv", "en"] as const).map((loc) => (
                  <fieldset
                    key={loc}
                    className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] p-4"
                  >
                    <legend className="px-1 text-[0.85rem] font-medium">
                      {languageLabel(loc, t)}
                    </legend>
                    <label className="mb-3 block">
                      <span className="mb-1 block text-[0.8rem]">
                        {t("configurations.editor.kindTone")}
                      </span>
                      <select
                        className="w-full rounded-[var(--radius-md)] border-[1.5px] border-[color:var(--border-hairline)] bg-white px-3 py-[9px] text-[0.85rem]"
                        value={anchorSets[loc].tone || ""}
                        onChange={(e) => setAnchorRef(loc, "tone", Number(e.target.value))}
                      >
                        <option value="">{t("configurations.editor.anchorPlaceholder")}</option>
                        {anchorOptions("tone", loc).map((row) => (
                          <option key={row.id} value={row.id}>
                            {row.name} — {row.version}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[0.8rem]">
                        {t("configurations.editor.kindStyle")}
                      </span>
                      <select
                        className="w-full rounded-[var(--radius-md)] border-[1.5px] border-[color:var(--border-hairline)] bg-white px-3 py-[9px] text-[0.85rem]"
                        value={anchorSets[loc].style || ""}
                        onChange={(e) => setAnchorRef(loc, "style", Number(e.target.value))}
                      >
                        <option value="">{t("configurations.editor.anchorPlaceholder")}</option>
                        {anchorOptions("style", loc).map((row) => (
                          <option key={row.id} value={row.id}>
                            {row.name} — {row.version}
                          </option>
                        ))}
                      </select>
                    </label>
                  </fieldset>
                ))}
              </div>
              <p className="mt-4">
                <Link to="/tools/anchor-sets" className="text-[12.5px]">
                  {t("configurations.editor.anchorManage")}
                </Link>
              </p>
            </div>
          ) : null}

          {topTab === "grunddata" ? (
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
          ) : null}
        </div>
      )}
    </>
  )
}
