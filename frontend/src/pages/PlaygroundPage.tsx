import { useEffect, useMemo, useState } from "react"
import {
  getConfiguration,
  getPromptCatalog,
  listConfigurations,
  type Configuration,
  type PromptCatalog,
} from "@/api/configurations"
import {
  comparePlaygroundSsr,
  getPlaygroundAnchors,
  ratePlaygroundSsr,
  runPlaygroundPrompt,
  type AnchorsResponse,
  type CompareResponse,
  type PlaygroundDimension,
  type PlaygroundLocale,
  type PromptRunResponse,
  type RateResponse,
} from "@/api/playground"
import { PlaygroundToolsPanel } from "@/components/playground/PlaygroundToolsPanel"
import { PlaygroundImagePanel } from "@/components/playground/PlaygroundImagePanel"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

type TabId = "anchors" | "prompts" | "compare" | "tools" | "image"

type VarRow = { key: string; value: string }

function parseTextLines(raw: string): string[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
}

function extractPlaceholders(text: string): string[] {
  const keys = new Set<string>()
  const re = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g
  let match: RegExpExecArray | null
  while ((match = re.exec(text)) !== null) {
    keys.add(match[1])
  }
  return [...keys]
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

function pct(rate: number): string {
  return String(Math.round(rate * 1000) / 10)
}

export function PlaygroundPage() {
  const { t } = useLocale()
  const [tab, setTab] = useState<TabId>("anchors")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [anchorsPayload, setAnchorsPayload] = useState<AnchorsResponse | null>(null)
  const [dimension, setDimension] = useState<PlaygroundDimension>("tone")
  const [anchorLocale, setAnchorLocale] = useState<PlaygroundLocale>("sv")
  const [temperature, setTemperature] = useState(0.1)
  const [labels, setLabels] = useState<string[]>([])
  const [statements, setStatements] = useState<string[]>([])
  const [textsRaw, setTextsRaw] = useState("")
  const [useHumanLabels, setUseHumanLabels] = useState(false)
  const [humanLabels, setHumanLabels] = useState<string[]>([])
  const [rateResult, setRateResult] = useState<RateResponse | null>(null)
  const [compareResult, setCompareResult] = useState<CompareResponse | null>(null)
  const [lastTemperature, setLastTemperature] = useState<number | null>(null)

  const [configs, setConfigs] = useState<Configuration[]>([])
  const [catalog, setCatalog] = useState<PromptCatalog | null>(null)
  const [configId, setConfigId] = useState<number | null>(null)
  const [promptKey, setPromptKey] = useState("")
  const [promptA, setPromptA] = useState("")
  const [promptB, setPromptB] = useState("")
  const [varRows, setVarRows] = useState<VarRow[]>([])
  const [userMessage, setUserMessage] = useState("")
  const [promptResult, setPromptResult] = useState<PromptRunResponse | null>(null)

  const textLines = useMemo(() => parseTextLines(textsRaw), [textsRaw])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [anchors, configList, promptCatalog] = await Promise.all([
          getPlaygroundAnchors(),
          listConfigurations(),
          getPromptCatalog({ label_locale: "sv" }),
        ])
        if (cancelled) return
        setAnchorsPayload(anchors)
        setConfigs(configList)
        setCatalog(promptCatalog)
        const active = configList.find((c) => c.is_active) ?? configList[0]
        if (active) setConfigId(active.id)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!anchorsPayload) return
    const set = anchorsPayload[dimension][anchorLocale]
    setLabels([...set.labels])
    setStatements([...set.statements])
  }, [anchorsPayload, dimension, anchorLocale])

  useEffect(() => {
    setHumanLabels((prev) => {
      const next = textLines.map((_, i) => prev[i] ?? "")
      return next
    })
  }, [textLines])

  useEffect(() => {
    if (configId == null) return
    let cancelled = false
    ;(async () => {
      try {
        const cfg = await getConfiguration(configId)
        if (cancelled) return
        const keys = Object.keys(cfg.prompts)
        const nextKey = keys[0] ?? ""
        setPromptKey(nextKey)
        const text = nextKey ? (cfg.prompts[nextKey] ?? "") : ""
        setPromptA(text)
        setPromptB(text)
        setVarRows(extractPlaceholders(text).map((key) => ({ key, value: "" })))
        setPromptResult(null)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [configId])

  async function onPromptKeyChange(nextKey: string) {
    setPromptKey(nextKey)
    if (configId == null) return
    try {
      const cfg = await getConfiguration(configId)
      const text = cfg.prompts[nextKey] ?? ""
      setPromptA(text)
      setPromptB(text)
      setVarRows(extractPlaceholders(text).map((key) => ({ key, value: "" })))
      setPromptResult(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function resetAnchors() {
    if (!anchorsPayload) return
    const set = anchorsPayload[dimension][anchorLocale]
    setLabels([...set.labels])
    setStatements([...set.statements])
  }

  async function onRunRate() {
    setError(null)
    setRateResult(null)
    if (textLines.length === 0) {
      setError(t("playground.emptyTexts"))
      return
    }
    if (useHumanLabels && humanLabels.some((h) => !h)) {
      setError(t("playground.humanLabelsRequired"))
      return
    }
    if (!(temperature > 0)) {
      setError(t("playground.temperatureInvalid"))
      return
    }
    setBusy(true)
    try {
      const result = await ratePlaygroundSsr({
        texts: textLines,
        dimension,
        locale: anchorLocale,
        labels,
        statements,
        temperature,
        human_labels: useHumanLabels ? humanLabels : undefined,
      })
      setRateResult(result)
      setLastTemperature(temperature)
    } catch (err) {
      setError(t("playground.error", { message: errorMessage(err) }))
    } finally {
      setBusy(false)
    }
  }

  async function onRunCompare() {
    setError(null)
    setCompareResult(null)
    if (textLines.length === 0) {
      setError(t("playground.emptyTexts"))
      return
    }
    if (!(temperature > 0)) {
      setError(t("playground.temperatureInvalid"))
      return
    }
    setBusy(true)
    try {
      const toneSet = anchorsPayload?.tone[anchorLocale]
      const useEditedTone = dimension === "tone" && labels.length > 0
      const result = await comparePlaygroundSsr({
        texts: textLines,
        locale: anchorLocale,
        labels: useEditedTone ? labels : toneSet?.labels,
        statements: useEditedTone ? statements : toneSet?.statements,
        temperature,
      })
      setCompareResult(result)
      setLastTemperature(temperature)
    } catch (err) {
      setError(t("playground.error", { message: errorMessage(err) }))
    } finally {
      setBusy(false)
    }
  }

  async function onRunPrompts(withB: boolean) {
    setError(null)
    setPromptResult(null)
    if (configId == null || !promptKey) return
    setBusy(true)
    try {
      const variables: Record<string, string> = {}
      for (const row of varRows) {
        if (row.key.trim()) variables[row.key.trim()] = row.value
      }
      const result = await runPlaygroundPrompt({
        configuration_id: configId,
        prompt_key: promptKey,
        prompt_override: withB ? promptB : null,
        variables,
        user_message: userMessage.trim() || null,
      })
      setPromptResult(result)
    } catch (err) {
      setError(t("playground.error", { message: errorMessage(err) }))
    } finally {
      setBusy(false)
    }
  }

  const promptKeys = useMemo(() => {
    if (configId == null) return [] as string[]
    const cfg = configs.find((c) => c.id === configId)
    if (!cfg) return []
    return Object.keys(cfg.prompts)
  }, [configId, configs])

  const fieldLabel = (key: string) =>
    catalog?.fields.find((f) => f.key === key)?.label ?? key

  const tabs: {
    id: TabId
    labelKey:
      | "playground.tabAnchors"
      | "playground.tabPrompts"
      | "playground.tabCompare"
      | "playground.tabTools"
      | "playground.tabImage"
  }[] = [
    { id: "anchors", labelKey: "playground.tabAnchors" },
    { id: "prompts", labelKey: "playground.tabPrompts" },
    { id: "compare", labelKey: "playground.tabCompare" },
    { id: "image", labelKey: "playground.tabImage" },
    { id: "tools", labelKey: "playground.tabTools" },
  ]

  return (
    <div>
        <div className="mb-4">
          <h2 className="text-lg font-medium">{t("playground.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("playground.subtitle")}</p>
        </div>

        <div
          role="tablist"
          aria-label={t("playground.tablistAria")}
          className="mb-4 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
        >
          {tabs.map((item) => {
            const selected = tab === item.id
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                id={`playground-tab-${item.id}`}
                aria-selected={selected}
                aria-controls={`playground-panel-${item.id}`}
                tabIndex={selected ? 0 : -1}
                className={
                  selected
                    ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium text-[color:var(--text-body)]"
                    : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                }
                onClick={() => {
                  setTab(item.id)
                  setError(null)
                }}
              >
                {t(item.labelKey)}
              </button>
            )
          })}
        </div>

        {error ? (
          <div className="mb-4 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm" role="alert">
            {error}
          </div>
        ) : null}

        {tab === "anchors" ? (
          <section
            id="playground-panel-anchors"
            role="tabpanel"
            aria-labelledby="playground-tab-anchors"
            className="space-y-6"
          >
            <div className="flex flex-wrap gap-4">
              <label className="grid gap-1 text-sm">
                <span>{t("playground.dimension")}</span>
                <select
                  className="min-w-[10rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
                  value={dimension}
                  onChange={(e) => setDimension(e.target.value as PlaygroundDimension)}
                >
                  <option value="tone">{t("playground.dimensionTone")}</option>
                  <option value="style">{t("playground.dimensionStyle")}</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span>{t("playground.locale")}</span>
                <select
                  className="min-w-[10rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
                  value={anchorLocale}
                  onChange={(e) => setAnchorLocale(e.target.value as PlaygroundLocale)}
                >
                  <option value="sv">{t("playground.localeSv")}</option>
                  <option value="en">{t("playground.localeEn")}</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span>{t("playground.temperature")}</span>
                <input
                  type="number"
                  min={0.01}
                  max={2}
                  step={0.05}
                  list="playground-temperature-presets"
                  className="w-28 rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono"
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
              </label>
              <datalist id="playground-temperature-presets">
                <option value="0.05" />
                <option value="0.1" />
                <option value="0.2" />
                <option value="0.5" />
                <option value="1" />
              </datalist>
              <div className="flex items-end">
                <Button type="button" variant="outline" size="sm" onClick={resetAnchors}>
                  {t("playground.resetAnchors")}
                </Button>
              </div>
            </div>
            <p className="text-sm text-muted-foreground">{t("playground.temperatureHint")}</p>

            <div>
              <h2 className="mb-2 text-base font-medium">{t("playground.anchorsHeading")}</h2>
              <div className="space-y-3">
                {labels.map((label, i) => (
                  <label key={`${label}-${i}`} className="grid gap-1 text-sm">
                    <span className="text-muted-foreground">{label}</span>
                    <textarea
                      className="min-h-[4rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono text-xs"
                      value={statements[i] ?? ""}
                      onChange={(e) => {
                        const next = [...statements]
                        next[i] = e.target.value
                        setStatements(next)
                      }}
                    />
                  </label>
                ))}
              </div>
            </div>

            <div>
              <h2 className="mb-1 text-base font-medium">{t("playground.textsHeading")}</h2>
              <p className="mb-2 text-sm text-muted-foreground">{t("playground.textsHint")}</p>
              <textarea
                className="min-h-[8rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm"
                placeholder={t("playground.textsPlaceholder")}
                value={textsRaw}
                onChange={(e) => setTextsRaw(e.target.value)}
              />
              <label className="mt-2 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={useHumanLabels}
                  onChange={(e) => setUseHumanLabels(e.target.checked)}
                />
                {t("playground.useHumanLabels")}
              </label>
              {useHumanLabels && textLines.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {textLines.map((line, i) => (
                    <div key={`hl-${i}`} className="grid gap-1 sm:grid-cols-[1fr_14rem] sm:items-center">
                      <div className="truncate text-sm text-muted-foreground" title={line}>
                        {line}
                      </div>
                      <label className="grid gap-1 text-sm">
                        <span className="sr-only">{t("playground.humanLabelFor", { n: i + 1 })}</span>
                        <select
                          className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
                          value={humanLabels[i] ?? ""}
                          onChange={(e) => {
                            const next = [...humanLabels]
                            next[i] = e.target.value
                            setHumanLabels(next)
                          }}
                        >
                          <option value="">{t("playground.humanLabelNone")}</option>
                          {labels.map((lab) => (
                            <option key={lab} value={lab}>
                              {lab}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="mt-3">
                <Button type="button" disabled={busy} onClick={() => void onRunRate()}>
                  {busy ? t("playground.running") : t("playground.runRate")}
                </Button>
              </div>
            </div>

            {rateResult ? (
              <div className="space-y-4">
                {lastTemperature != null ? (
                  <p className="text-sm text-muted-foreground">
                    {t("playground.temperatureUsed", { value: String(lastTemperature) })}
                  </p>
                ) : null}
                {rateResult.accuracy != null ? (
                  <p className="text-sm font-medium">
                    {t("playground.accuracy", { pct: pct(rateResult.accuracy) })}
                  </p>
                ) : null}
                <div>
                  <h2 className="mb-2 text-base font-medium">{t("playground.sharesHeading")}</h2>
                  <ul className="grid gap-1 text-sm sm:grid-cols-2">
                    {Object.entries(rateResult.shares).map(([lab, share]) => (
                      <li key={lab} className="flex justify-between gap-4 border-b border-[color:var(--border-hairline)] py-1">
                        <span>{lab}</span>
                        <span className="font-mono">{pct(share)}%</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h2 className="mb-2 text-base font-medium">{t("playground.resultsHeading")}</h2>
                  <div className="space-y-3">
                    {rateResult.per_text.map((row, i) => (
                      <div
                        key={`rt-${i}`}
                        className="rounded border border-[color:var(--border-hairline)] px-3 py-2 text-sm"
                      >
                        <div className="mb-1 font-medium">{row.text}</div>
                        <div className="text-muted-foreground">
                          {t("playground.predicted")}: {row.predicted_label}
                        </div>
                        <ul className="mt-1 grid gap-0.5 font-mono text-xs sm:grid-cols-2">
                          {Object.entries(row.pmf).map(([lab, p]) => (
                            <li key={lab}>
                              {lab}: {pct(p)}%
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
                {rateResult.confusion ? (
                  <div>
                    <h2 className="mb-2 text-base font-medium">{t("playground.confusionHeading")}</h2>
                    <pre className="overflow-auto rounded border border-[color:var(--border-hairline)] p-3 text-xs">
                      {JSON.stringify(rateResult.confusion, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "prompts" ? (
          <section
            id="playground-panel-prompts"
            role="tabpanel"
            aria-labelledby="playground-tab-prompts"
            className="space-y-6"
          >
            {configs.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("playground.noConfigs")}</p>
            ) : (
              <>
                <div className="flex flex-wrap gap-4">
                  <label className="grid gap-1 text-sm">
                    <span>{t("playground.config")}</span>
                    <select
                      className="min-w-[14rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
                      value={configId ?? ""}
                      onChange={(e) => setConfigId(Number(e.target.value))}
                    >
                      {configs.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                          {c.is_active ? " ★" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-1 text-sm">
                    <span>{t("playground.promptKey")}</span>
                    <select
                      className="min-w-[18rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
                      value={promptKey}
                      onChange={(e) => void onPromptKeyChange(e.target.value)}
                      disabled={promptKeys.length === 0}
                    >
                      {promptKeys.length === 0 ? (
                        <option value="">{t("playground.noPromptKeys")}</option>
                      ) : (
                        promptKeys.map((key) => (
                          <option key={key} value={key}>
                            {fieldLabel(key)}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <label className="grid gap-1 text-sm">
                    <span>{t("playground.promptA")}</span>
                    <textarea
                      className="min-h-[12rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono text-xs"
                      value={promptA}
                      readOnly
                    />
                  </label>
                  <div className="grid gap-1 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span>{t("playground.promptB")}</span>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setPromptB(promptA)}
                      >
                        {t("playground.fillBFromA")}
                      </Button>
                    </div>
                    <textarea
                      className="min-h-[12rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono text-xs"
                      value={promptB}
                      onChange={(e) => setPromptB(e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h2 className="text-base font-medium">{t("playground.variablesHeading")}</h2>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setVarRows((rows) => [...rows, { key: "", value: "" }])}
                    >
                      {t("playground.addVariable")}
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {varRows.map((row, i) => (
                      <div key={`var-${i}`} className="grid gap-2 sm:grid-cols-2">
                        <label className="grid gap-1 text-sm">
                          <span className="sr-only">{t("playground.variableKey")}</span>
                          <input
                            className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono text-xs"
                            placeholder={t("playground.variableKey")}
                            value={row.key}
                            onChange={(e) => {
                              const next = [...varRows]
                              next[i] = { ...next[i], key: e.target.value }
                              setVarRows(next)
                            }}
                          />
                        </label>
                        <label className="grid gap-1 text-sm">
                          <span className="sr-only">{t("playground.variableValue")}</span>
                          <input
                            className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-xs"
                            placeholder={t("playground.variableValue")}
                            value={row.value}
                            onChange={(e) => {
                              const next = [...varRows]
                              next[i] = { ...next[i], value: e.target.value }
                              setVarRows(next)
                            }}
                          />
                        </label>
                      </div>
                    ))}
                  </div>
                </div>

                <label className="grid gap-1 text-sm">
                  <span>{t("playground.userMessage")}</span>
                  <textarea
                    className="min-h-[4rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm"
                    placeholder={t("playground.userMessagePlaceholder")}
                    value={userMessage}
                    onChange={(e) => setUserMessage(e.target.value)}
                  />
                </label>

                <div className="flex flex-wrap gap-2">
                  <Button type="button" disabled={busy || !promptKey} onClick={() => void onRunPrompts(true)}>
                    {busy ? t("playground.running") : t("playground.runPrompts")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy || !promptKey}
                    onClick={() => void onRunPrompts(false)}
                  >
                    {t("playground.runPromptAOnly")}
                  </Button>
                </div>

                {promptResult ? (
                  <div className="grid gap-4 lg:grid-cols-2">
                    {promptResult.variants.map((v) => (
                      <div
                        key={v.id}
                        className="space-y-2 rounded border border-[color:var(--border-hairline)] p-3"
                      >
                        <h3 className="font-medium">
                          {v.id === "A" ? t("playground.variantA") : t("playground.variantB")}
                        </h3>
                        <div>
                          <div className="mb-1 text-xs text-muted-foreground">
                            {t("playground.renderedHeading")}
                          </div>
                          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-black/20 p-2 text-xs">
                            {v.rendered_prompt}
                          </pre>
                        </div>
                        <div>
                          <div className="mb-1 text-xs text-muted-foreground">
                            {t("playground.responseHeading")}
                          </div>
                          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-black/20 p-2 text-sm">
                            {v.response}
                          </pre>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </section>
        ) : null}

        {tab === "compare" ? (
          <section
            id="playground-panel-compare"
            role="tabpanel"
            aria-labelledby="playground-tab-compare"
            className="space-y-6"
          >
            <p className="text-sm text-muted-foreground">{t("playground.compareHint")}</p>
            <div className="flex flex-wrap gap-4">
              <label className="grid gap-1 text-sm">
                <span>{t("playground.locale")}</span>
                <select
                  className="min-w-[10rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
                  value={anchorLocale}
                  onChange={(e) => setAnchorLocale(e.target.value as PlaygroundLocale)}
                >
                  <option value="sv">{t("playground.localeSv")}</option>
                  <option value="en">{t("playground.localeEn")}</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span>{t("playground.temperature")}</span>
                <input
                  type="number"
                  min={0.01}
                  max={2}
                  step={0.05}
                  list="playground-temperature-presets-compare"
                  className="w-28 rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono"
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
              </label>
              <datalist id="playground-temperature-presets-compare">
                <option value="0.05" />
                <option value="0.1" />
                <option value="0.2" />
                <option value="0.5" />
                <option value="1" />
              </datalist>
            </div>
            <p className="text-sm text-muted-foreground">{t("playground.temperatureHint")}</p>
            <div>
              <h2 className="mb-1 text-base font-medium">{t("playground.textsHeading")}</h2>
              <p className="mb-2 text-sm text-muted-foreground">{t("playground.textsHint")}</p>
              <textarea
                className="min-h-[8rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm"
                placeholder={t("playground.textsPlaceholder")}
                value={textsRaw}
                onChange={(e) => setTextsRaw(e.target.value)}
              />
              <div className="mt-3">
                <Button type="button" disabled={busy} onClick={() => void onRunCompare()}>
                  {busy ? t("playground.running") : t("playground.runCompare")}
                </Button>
              </div>
            </div>

            {compareResult ? (
              <div className="space-y-4">
                {lastTemperature != null ? (
                  <p className="text-sm text-muted-foreground">
                    {t("playground.temperatureUsed", { value: String(lastTemperature) })}
                  </p>
                ) : null}
                <p className="text-sm font-medium">
                  {t("playground.agreement", { pct: pct(compareResult.agreement_rate) })}
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[color:var(--border-hairline)]">
                        <th className="px-2 py-1.5 font-medium">{t("playground.colText")}</th>
                        <th className="px-2 py-1.5 font-medium">{t("playground.colSsr")}</th>
                        <th className="px-2 py-1.5 font-medium">{t("playground.colSsrBucket")}</th>
                        <th className="px-2 py-1.5 font-medium">{t("playground.colLexicon")}</th>
                        <th className="px-2 py-1.5 font-medium">{t("playground.colMatch")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {compareResult.rows.map((row, i) => (
                        <tr
                          key={`cmp-${i}`}
                          className="border-b border-[color:var(--border-hairline)] align-top"
                        >
                          <td className="px-2 py-1.5">{row.text}</td>
                          <td className="px-2 py-1.5">{row.ssr_label}</td>
                          <td className="px-2 py-1.5">{row.ssr_bucket}</td>
                          <td className="px-2 py-1.5">{row.lexicon_label}</td>
                          <td
                            className={cn(
                              "px-2 py-1.5",
                              row.match ? "text-emerald-400" : "text-amber-400",
                            )}
                          >
                            {row.match ? t("playground.matchYes") : t("playground.matchNo")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "tools" ? <PlaygroundToolsPanel /> : null}

        {tab === "image" ? <PlaygroundImagePanel /> : null}
    </div>
  )
}
