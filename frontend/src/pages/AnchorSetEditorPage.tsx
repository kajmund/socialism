import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createAnchorSet,
  createCalibrationItem,
  deleteAnchorPoolItem,
  deleteCalibrationItem,
  getAnchorSet,
  listCalibrationItems,
  listMisclassificationFlags,
  listPoolItems,
  runAnchorCalibration,
  testAnchorSet,
  updateAnchorSet,
  updateMisclassificationFlag,
  type AnchorKind,
  type AnchorLocale,
  type AnchorTestResponse,
  type SsrAnchorCalibrationItem,
  type SsrAnchorPoolItem,
  type SsrMisclassificationFlag,
} from "@/api/anchorSets"
import { getLabelVocabulary } from "@/api/labelVocabularies"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type EditorTab = "anchors" | "pool" | "flagged" | "calibration" | "test"

function emptyStatements(count: number): string[] {
  return Array.from({ length: count }, () => "")
}

function labelSelectOptions(current: string, vocabLabels: string[]): string[] {
  if (!current || vocabLabels.includes(current)) return vocabLabels
  return [current, ...vocabLabels]
}

function poolSourceLabel(
  sourceType: SsrAnchorPoolItem["source_type"],
  t: (key: MessageKey) => string,
): string {
  switch (sourceType) {
    case "comment":
      return t("anchorSets.pool.sourceComment")
    case "tick_interview":
      return t("anchorSets.pool.sourceTickInterview")
    case "posthoc_interview":
      return t("anchorSets.pool.sourcePosthocInterview")
    default: {
      const _exhaustive: never = sourceType
      return _exhaustive
    }
  }
}

export function AnchorSetEditorPage() {
  const { t, intl } = useLocale()
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id?: string }>()
  const isEdit = Boolean(editId)
  const numericId = editId ? Number(editId) : NaN

  const [tab, setTab] = useState<EditorTab>("anchors")
  const [name, setName] = useState("")
  const [kind, setKind] = useState<AnchorKind>("tone")
  const [locale, setLocale] = useState<AnchorLocale>("sv")
  const [version, setVersion] = useState("v1")
  const [labels, setLabels] = useState<string[]>([])
  const [statements, setStatements] = useState<string[]>([])
  const [vocabLabels, setVocabLabels] = useState<string[]>([])
  const [status, setStatus] = useState<"draft" | "published">("draft")
  const [validationStatus, setValidationStatus] = useState<
    "untested" | "ok" | "stale" | "low"
  >("untested")
  const [storedMacroAccuracy, setStoredMacroAccuracy] = useState<number | null>(null)
  const [calibrationItemCount, setCalibrationItemCount] = useState(0)
  const [calibration, setCalibration] = useState<SsrAnchorCalibrationItem[]>([])
  const [poolItems, setPoolItems] = useState<SsrAnchorPoolItem[]>([])
  const [poolSearch, setPoolSearch] = useState("")
  const [poolLabelFilter, setPoolLabelFilter] = useState("")
  const [flaggedItems, setFlaggedItems] = useState<SsrMisclassificationFlag[]>([])
  const [flaggedLoading, setFlaggedLoading] = useState(false)
  const [flagActionId, setFlagActionId] = useState<number | null>(null)
  const [testTexts, setTestTexts] = useState("")
  const [testResult, setTestResult] = useState<AnchorTestResponse | null>(null)
  const [newCalText, setNewCalText] = useState("")
  const [newCalLabel, setNewCalLabel] = useState("")
  const [loading, setLoading] = useState(isEdit)
  const [vocabLoading, setVocabLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isEdit || Number.isNaN(numericId)) return
    let cancelled = false
    setLoading(true)
    Promise.all([getAnchorSet(numericId), listCalibrationItems(numericId)])
      .then(([row, items]) => {
        if (cancelled) return
        setName(row.name)
        setKind(row.kind)
        setLocale(row.locale)
        setVersion(row.version)
        setLabels(row.labels)
        setStatements(row.statements)
        setStatus(row.status)
        setValidationStatus(row.validation_status)
        setStoredMacroAccuracy(row.calibration_accuracy)
        setCalibrationItemCount(row.calibration_item_count)
        setCalibration(items)
        if (row.labels[0]) setNewCalLabel(row.labels[0])
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("anchorSets.editor.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId, t])

  useEffect(() => {
    let cancelled = false
    setVocabLoading(true)
    getLabelVocabulary(kind, locale)
      .then((vocab) => {
        if (cancelled) return
        const nextLabels = vocab.entries.map((entry) => entry.label)
        setVocabLabels(nextLabels)
        if (!isEdit) {
          setLabels(nextLabels)
          setStatements(emptyStatements(nextLabels.length))
          if (nextLabels[0]) setNewCalLabel(nextLabels[0])
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("anchorSets.vocab.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setVocabLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [kind, locale, isEdit, t])

  // Prefetch for per-label pool counts on the anchors tab.
  useEffect(() => {
    if (!isEdit || Number.isNaN(numericId)) return
    let cancelled = false
    listPoolItems(numericId)
      .then((items) => {
        if (!cancelled) setPoolItems(items)
      })
      .catch(() => {
        /* counts are optional until the pool tab is opened */
      })
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId])

  // Load (or refresh) pool items when the pool tab is selected.
  useEffect(() => {
    if (!isEdit || Number.isNaN(numericId) || tab !== "pool") return
    let cancelled = false
    listPoolItems(numericId)
      .then((items) => {
        if (!cancelled) setPoolItems(items)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("anchorSets.editor.loadError"))
        }
      })
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId, tab, t])

  // Load open misclassification flags when the flagged tab is selected.
  useEffect(() => {
    if (!isEdit || Number.isNaN(numericId) || tab !== "flagged") return
    let cancelled = false
    setFlaggedLoading(true)
    listMisclassificationFlags(numericId, "open")
      .then((items) => {
        if (!cancelled) setFlaggedItems(items)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t("anchorSets.flagged.loadError"),
          )
        }
      })
      .finally(() => {
        if (!cancelled) setFlaggedLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isEdit, numericId, tab, t])

  const poolCountsByLabel = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of poolItems) {
      counts.set(item.label, (counts.get(item.label) ?? 0) + 1)
    }
    return counts
  }, [poolItems])

  const filteredPoolItems = useMemo(() => {
    const q = poolSearch.trim().toLowerCase()
    return poolItems.filter((item) => {
      if (poolLabelFilter && item.label !== poolLabelFilter) return false
      if (!q) return true
      return item.text.toLowerCase().includes(q) || item.label.toLowerCase().includes(q)
    })
  }, [poolItems, poolSearch, poolLabelFilter])

  function openPoolForLabel(label: string) {
    setPoolLabelFilter(label)
    setTab("pool")
  }

  function onKindChange(next: AnchorKind) {
    setKind(next)
  }

  async function save(event?: FormEvent) {
    event?.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (isEdit) {
        await updateAnchorSet(numericId, { name, version, labels, statements })
      } else {
        const created = await createAnchorSet({
          name,
          kind,
          locale,
          version,
          labels,
          statements,
          status: "draft",
        })
        navigate(`/tools/anchor-sets/${created.id}/edit`, { replace: true })
      }
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function addCalibration() {
    if (!isEdit) return
    try {
      const item = await createCalibrationItem(numericId, {
        text: newCalText,
        human_label: newCalLabel,
      })
      setCalibration((prev) => [...prev, item])
      setNewCalText("")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  async function removeCalibration(itemId: number) {
    if (!isEdit) return
    await deleteCalibrationItem(numericId, itemId)
    setCalibration((prev) => prev.filter((i) => i.id !== itemId))
  }

  async function removePoolItem(itemId: number) {
    if (!isEdit) return
    try {
      await deleteAnchorPoolItem(numericId, itemId)
      setPoolItems((prev) => prev.filter((i) => i.id !== itemId))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  async function resolveFlag(flagId: number) {
    if (!isEdit) return
    setFlagActionId(flagId)
    setError(null)
    try {
      await updateMisclassificationFlag(numericId, flagId, {
        status: "resolved",
      })
      setFlaggedItems((prev) => prev.filter((f) => f.id !== flagId))
      const items = await listPoolItems(numericId)
      setPoolItems(items)
    } catch (err: unknown) {
      setError(
        err instanceof ApiError ? err.message : t("anchorSets.flagged.actionError"),
      )
    } finally {
      setFlagActionId(null)
    }
  }

  async function dismissFlag(flagId: number) {
    if (!isEdit) return
    setFlagActionId(flagId)
    setError(null)
    try {
      await updateMisclassificationFlag(numericId, flagId, { status: "dismissed" })
      setFlaggedItems((prev) => prev.filter((f) => f.id !== flagId))
    } catch (err: unknown) {
      setError(
        err instanceof ApiError ? err.message : t("anchorSets.flagged.actionError"),
      )
    } finally {
      setFlagActionId(null)
    }
  }

  async function persistCalibrationRun() {
    if (!isEdit) return
    setError(null)
    try {
      const result = await runAnchorCalibration(numericId)
      setTestResult(result)
      const refreshed = await getAnchorSet(numericId)
      setValidationStatus(refreshed.validation_status)
      setStoredMacroAccuracy(refreshed.calibration_accuracy)
      setCalibrationItemCount(refreshed.calibration_item_count)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("anchorSets.test.error"))
    }
  }

  async function runTest(useCalibration: boolean) {
    if (!isEdit) return
    setError(null)
    try {
      const texts = testTexts
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
      const result = await testAnchorSet(numericId, {
        texts: texts.length ? texts : [" "],
        use_calibration: useCalibration,
        temperature: 0.1,
      })
      setTestResult(result)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("anchorSets.test.error"))
    }
  }

  const readOnly = status === "published"

  const tabEntries: { id: EditorTab; labelKey: MessageKey }[] = [
    { id: "anchors", labelKey: "anchorSets.editor.tabAnchors" },
    ...(isEdit
      ? [
          { id: "pool" as const, labelKey: "anchorSets.editor.tabPool" as MessageKey },
          {
            id: "flagged" as const,
            labelKey: "anchorSets.editor.tabFlagged" as MessageKey,
          },
        ]
      : []),
    { id: "calibration", labelKey: "anchorSets.editor.tabCalibration" },
    { id: "test", labelKey: "anchorSets.editor.tabTest" },
  ]

  return (
    <div className="space-y-6">
      <div className="text-sm text-muted-foreground">
        <Link to="/tools/anchor-sets">{t("anchorSets.list.title")}</Link>
        <span className="mx-2">/</span>
        <span>
          {isEdit ? t("anchorSets.editor.editTitle") : t("anchorSets.editor.newTitle")}
        </span>
      </div>

      <div className="head-row">
        <div>
          <h1>
            {isEdit ? t("anchorSets.editor.editTitle") : t("anchorSets.editor.newTitle")}
          </h1>
          <p className="muted">{t("anchorSets.editor.intro")}</p>
          {isEdit ? (
            <p className="text-xs text-muted-foreground">
              {t("anchorSets.editor.validationSummary", {
                count: calibrationItemCount,
                status: t(`anchorSets.validation.${validationStatus}`),
                pct:
                  storedMacroAccuracy != null
                    ? String(Math.round(storedMacroAccuracy * 1000) / 10)
                    : "—",
              })}
            </p>
          ) : null}
        </div>
      </div>

      {loading && <p className="muted">{t("anchorSets.editor.loading")}</p>}
      {error && <p className="text-destructive">{error}</p>}

      {!loading && (
        <>
          <div
            role="tablist"
            className="flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
          >
            {tabEntries.map(({ id, labelKey }) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                className={
                  tab === id
                    ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium"
                    : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground"
                }
                onClick={() => setTab(id)}
              >
                {t(labelKey)}
              </button>
            ))}
          </div>

          {tab === "anchors" ? (
            <form className="max-w-3xl space-y-4" onSubmit={(e) => void save(e)}>
              <label className="block space-y-1">
                <span className="text-sm font-medium">{t("anchorSets.editor.nameLabel")}</span>
                <input
                  className="dsearch w-full"
                  value={name}
                  disabled={readOnly}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-3">
                <label className="block space-y-1">
                  <span className="text-sm font-medium">{t("anchorSets.editor.kindLabel")}</span>
                  <select
                    className="dsel w-full"
                    value={kind}
                    disabled={isEdit}
                    onChange={(e) => onKindChange(e.target.value as AnchorKind)}
                  >
                    <option value="tone">{t("anchorSets.kindTone")}</option>
                    <option value="style">{t("anchorSets.kindStyle")}</option>
                  </select>
                </label>
                <label className="block space-y-1">
                  <span className="text-sm font-medium">{t("anchorSets.editor.localeLabel")}</span>
                  <select
                    className="dsel w-full"
                    value={locale}
                    disabled={isEdit}
                    onChange={(e) => setLocale(e.target.value as AnchorLocale)}
                  >
                    <option value="sv">{t("configurations.language.sv")}</option>
                    <option value="en">{t("configurations.language.en")}</option>
                  </select>
                </label>
                <label className="block space-y-1">
                  <span className="text-sm font-medium">{t("anchorSets.editor.versionLabel")}</span>
                  <input
                    className="dsearch w-full"
                    value={version}
                    disabled={readOnly}
                    onChange={(e) => setVersion(e.target.value)}
                  />
                </label>
              </div>

              <div className="space-y-3">
                <div className="text-sm font-medium">{t("anchorSets.editor.pairsTitle")}</div>
                {vocabLoading && labels.length === 0 ? (
                  <p className="muted text-sm">{t("anchorSets.list.loading")}</p>
                ) : null}
                {labels.map((label, idx) => {
                  const poolCount = poolCountsByLabel.get(label) ?? 0
                  const options = labelSelectOptions(label, vocabLabels)
                  return (
                    <div key={idx} className="grid gap-2 rounded border p-3 sm:grid-cols-2">
                      <label className="block space-y-1">
                        <span className="text-xs text-muted-foreground">
                          {t("anchorSets.editor.labelField")}
                        </span>
                        <select
                          className="dsel w-full"
                          value={label}
                          disabled={readOnly || vocabLoading || options.length === 0}
                          onChange={(e) => {
                            const next = [...labels]
                            next[idx] = e.target.value
                            setLabels(next)
                          }}
                        >
                          {options.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block space-y-1">
                        <span className="text-xs text-muted-foreground">
                          {t("anchorSets.editor.statementField")}
                        </span>
                        <textarea
                          className="dsearch w-full min-h-[72px]"
                          value={statements[idx] ?? ""}
                          disabled={readOnly}
                          onChange={(e) => {
                            const next = [...statements]
                            next[idx] = e.target.value
                            setStatements(next)
                          }}
                        />
                      </label>
                      {isEdit && poolCount > 0 ? (
                        <div className="sm:col-span-2">
                          <button
                            type="button"
                            className="text-xs text-muted-foreground underline hover:text-[color:var(--text-body)]"
                            onClick={() => openPoolForLabel(label)}
                          >
                            {t("anchorSets.editor.poolCount", { count: poolCount })}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>

              {!readOnly ? (
                <AdminButton type="submit" variant="primary" disabled={saving}>
                  {saving ? t("common.saving") : t("common.save")}
                </AdminButton>
              ) : (
                <p className="text-sm text-muted-foreground">{t("anchorSets.editor.publishedHint")}</p>
              )}
            </form>
          ) : null}

          {tab === "pool" && isEdit ? (
            <div className="max-w-3xl space-y-4">
              <p className="text-sm text-muted-foreground">{t("anchorSets.pool.intro")}</p>
              <div className="flex flex-wrap gap-2">
                <input
                  className="dsearch min-w-[12rem] flex-1"
                  value={poolSearch}
                  onChange={(e) => setPoolSearch(e.target.value)}
                  placeholder={t("anchorSets.pool.searchPlaceholder")}
                />
                <select
                  className="dsel"
                  value={poolLabelFilter}
                  onChange={(e) => setPoolLabelFilter(e.target.value)}
                >
                  <option value="">{t("anchorSets.pool.allLabels")}</option>
                  {labels.map((label) => (
                    <option key={label} value={label}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              {filteredPoolItems.length === 0 ? (
                <p className="muted">{t("anchorSets.pool.empty")}</p>
              ) : (
                <ul className="space-y-2">
                  {filteredPoolItems.map((item) => (
                    <li
                      key={item.id}
                      className="flex flex-wrap items-start justify-between gap-2 rounded border p-3 text-sm"
                    >
                      <div className="min-w-0 flex-1 space-y-1">
                        <div>{item.text}</div>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span className="rounded border border-[color:var(--border-hairline)] px-1.5 py-0.5 text-[color:var(--text-body)]">
                            {item.label}
                          </span>
                          <span>
                            {poolSourceLabel(item.source_type, t)}
                            {" · "}
                            {new Intl.DateTimeFormat(intl, {
                              dateStyle: "medium",
                              timeStyle: "short",
                            }).format(new Date(item.created_at))}
                          </span>
                        </div>
                      </div>
                      <AdminButton
                        type="button"
                        variant="secondary"
                        onClick={() => void removePoolItem(item.id)}
                      >
                        {t("anchorSets.pool.remove")}
                      </AdminButton>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}

          {tab === "flagged" && isEdit ? (
            <div className="max-w-3xl space-y-4">
              <p className="text-sm text-muted-foreground">{t("anchorSets.flagged.intro")}</p>
              {flaggedLoading ? (
                <p className="muted">{t("anchorSets.editor.loading")}</p>
              ) : flaggedItems.length === 0 ? (
                <p className="muted">{t("anchorSets.flagged.empty")}</p>
              ) : (
                <ul className="space-y-3">
                  {flaggedItems.map((flag) => {
                    const author =
                      typeof flag.source_ref.author === "string"
                        ? flag.source_ref.author
                        : null
                    return (
                      <li
                        key={flag.id}
                        className="space-y-2 rounded border p-4 text-sm"
                      >
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          {flag.source_run_id != null ? (
                            <span>
                              {t("anchorSets.flagged.runLabel", {
                                id: flag.source_run_id,
                              })}
                            </span>
                          ) : null}
                          {author ? <span>{author}</span> : null}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {t("anchorSets.flagged.systemSaid", {
                            label: flag.predicted_label,
                          })}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {t("anchorSets.flagged.expectedLabel", {
                            label: flag.expected_label,
                          })}
                        </p>
                        <p className="text-[color:var(--text-body)]">{flag.text}</p>
                        <div className="flex flex-wrap gap-2 pt-1">
                          <AdminButton
                            type="button"
                            variant="primary"
                            disabled={flagActionId === flag.id}
                            onClick={() => void resolveFlag(flag.id)}
                          >
                            {t("anchorSets.flagged.addAsAnchor")}
                          </AdminButton>
                          <AdminButton
                            type="button"
                            variant="secondary"
                            disabled={flagActionId === flag.id}
                            onClick={() => void dismissFlag(flag.id)}
                          >
                            {t("anchorSets.flagged.dismiss")}
                          </AdminButton>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          ) : null}

          {tab === "calibration" && isEdit ? (
            <div className="max-w-3xl space-y-4">
              <p className="text-sm text-muted-foreground">{t("anchorSets.calibration.intro")}</p>
              <ul className="space-y-2">
                {calibration.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-start justify-between gap-2 rounded border p-3 text-sm"
                  >
                    <div>
                      <div>{item.text}</div>
                      <div className="text-xs text-muted-foreground">{item.human_label}</div>
                    </div>
                    <AdminButton
                      type="button"
                      variant="secondary"
                      onClick={() => void removeCalibration(item.id)}
                    >
                      {t("common.delete")}
                    </AdminButton>
                  </li>
                ))}
              </ul>
              <div className="grid gap-2 sm:grid-cols-3">
                <textarea
                  className="dsearch min-h-[72px] sm:col-span-2"
                  placeholder={t("anchorSets.calibration.textPlaceholder")}
                  value={newCalText}
                  onChange={(e) => setNewCalText(e.target.value)}
                />
                <div className="space-y-2">
                  <select
                    className="dsel w-full"
                    value={newCalLabel}
                    onChange={(e) => setNewCalLabel(e.target.value)}
                  >
                    {labels.map((label) => (
                      <option key={label} value={label}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <AdminButton type="button" variant="primary" onClick={() => void addCalibration()}>
                    {t("anchorSets.calibration.add")}
                  </AdminButton>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <AdminButton type="button" variant="secondary" onClick={() => void persistCalibrationRun()}>
                  {t("anchorSets.calibration.runPersist")}
                </AdminButton>
              </div>
            </div>
          ) : null}

          {tab === "test" && isEdit ? (
            <div className="max-w-3xl space-y-4">
              <p className="text-sm text-muted-foreground">{t("anchorSets.test.intro")}</p>
              <textarea
                className="dsearch min-h-[120px] w-full"
                placeholder={t("anchorSets.test.textsPlaceholder")}
                value={testTexts}
                onChange={(e) => setTestTexts(e.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <AdminButton type="button" variant="primary" onClick={() => void runTest(false)}>
                  {t("anchorSets.test.run")}
                </AdminButton>
                <AdminButton type="button" variant="secondary" onClick={() => void runTest(true)}>
                  {t("anchorSets.test.runCalibration")}
                </AdminButton>
              </div>
              {testResult ? (
                <div className="space-y-3 text-sm">
                  {typeof testResult.macro_accuracy === "number" ? (
                    <p>
                      {t("anchorSets.test.macroAccuracy", {
                        pct: Math.round(testResult.macro_accuracy * 1000) / 10,
                      })}
                    </p>
                  ) : null}
                  {typeof testResult.accuracy === "number" ? (
                    <p>
                      {t("anchorSets.test.accuracy", {
                        pct: Math.round(testResult.accuracy * 1000) / 10,
                      })}
                    </p>
                  ) : null}
                  <pre className="overflow-auto rounded bg-muted p-3 text-xs">
                    {JSON.stringify(testResult, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
