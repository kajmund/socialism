import { useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createAnchorSet,
  createCalibrationItem,
  deleteCalibrationItem,
  getAnchorSet,
  listCalibrationItems,
  testAnchorSet,
  updateAnchorSet,
  type AnchorKind,
  type AnchorLocale,
  type AnchorTestResponse,
  type SsrAnchorCalibrationItem,
} from "@/api/anchorSets"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type EditorTab = "anchors" | "calibration" | "test"

const DEFAULT_TONE_LABELS_SV = [
  "Starkt negativ",
  "Något negativ",
  "Neutral",
  "Något positiv",
  "Starkt positiv",
]

const DEFAULT_STYLE_LABELS = [
  "Sarkastisk + konkret kritik",
  "Uppgiven + vardagsmetafor",
  "Fakta + yrkesauktoritet",
  "Personlig + hjärtlig berättelse",
  "Optimistisk / lösningsfokuserad",
  "Provocerande / konfronterande",
]

function defaultLabels(kind: AnchorKind): string[] {
  return kind === "tone" ? [...DEFAULT_TONE_LABELS_SV] : [...DEFAULT_STYLE_LABELS]
}

function defaultStatements(kind: AnchorKind): string[] {
  const n = kind === "tone" ? 5 : 6
  return Array.from({ length: n }, () => "")
}

export function AnchorSetEditorPage() {
  const { t } = useLocale()
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id?: string }>()
  const isEdit = Boolean(editId)
  const numericId = editId ? Number(editId) : NaN

  const [tab, setTab] = useState<EditorTab>("anchors")
  const [name, setName] = useState("")
  const [kind, setKind] = useState<AnchorKind>("tone")
  const [locale, setLocale] = useState<AnchorLocale>("sv")
  const [version, setVersion] = useState("v1")
  const [labels, setLabels] = useState<string[]>(defaultLabels("tone"))
  const [statements, setStatements] = useState<string[]>(defaultStatements("tone"))
  const [status, setStatus] = useState<"draft" | "published">("draft")
  const [calibration, setCalibration] = useState<SsrAnchorCalibrationItem[]>([])
  const [testTexts, setTestTexts] = useState("")
  const [testResult, setTestResult] = useState<AnchorTestResponse | null>(null)
  const [newCalText, setNewCalText] = useState("")
  const [newCalLabel, setNewCalLabel] = useState("")
  const [loading, setLoading] = useState(isEdit)
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

  function onKindChange(next: AnchorKind) {
    setKind(next)
    if (!isEdit) {
      setLabels(defaultLabels(next))
      setStatements(defaultStatements(next))
    }
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
            {(
              [
                ["anchors", "anchorSets.editor.tabAnchors"],
                ["calibration", "anchorSets.editor.tabCalibration"],
                ["test", "anchorSets.editor.tabTest"],
              ] as const
            ).map(([id, labelKey]) => (
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
                    <option value="nb">{t("configurations.language.nb")}</option>
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
                {labels.map((label, idx) => (
                  <div key={idx} className="grid gap-2 rounded border p-3 sm:grid-cols-2">
                    <label className="block space-y-1">
                      <span className="text-xs text-muted-foreground">
                        {t("anchorSets.editor.labelField")}
                      </span>
                      <input
                        className="dsearch w-full"
                        value={label}
                        disabled={readOnly}
                        onChange={(e) => {
                          const next = [...labels]
                          next[idx] = e.target.value
                          setLabels(next)
                        }}
                      />
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
                  </div>
                ))}
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
