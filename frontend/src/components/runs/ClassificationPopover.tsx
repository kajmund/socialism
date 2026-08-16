import { useEffect, useRef, useState, type MouseEvent } from "react"
import {
  createRunMisclassificationFlag,
  type RunTaggableTextRow,
} from "@/api/runs"
import { StarIcon } from "@/components/runs/AddAnchorModal"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { sourceRefKey } from "@/components/runs/useRunTaggableTexts"

type FlagKind = "tone" | "style"

type Props = {
  row: RunTaggableTextRow
  runId: number
  attemptId: string
  variantId: string
  toneOptions: string[]
  styleOptions: string[]
  reported: boolean
  onReported: () => void
}

export function ClassificationPopover({
  row,
  runId,
  attemptId,
  variantId,
  toneOptions,
  styleOptions,
  reported,
  onReported,
}: Props) {
  const { locale, t } = useLocale()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [picking, setPicking] = useState(false)
  const [kind, setKind] = useState<FlagKind | "">("")
  const [expected, setExpected] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canFlagTone = Boolean(row.tone_predicted)
  const canFlagStyle = Boolean(row.style_predicted)
  const availableKinds: FlagKind[] = [
    ...(canFlagTone ? (["tone"] as const) : []),
    ...(canFlagStyle ? (["style"] as const) : []),
  ]

  useEffect(() => {
    if (!open) return
    function onDocClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
        setPicking(false)
        setError(null)
      }
    }
    document.addEventListener("click", onDocClick)
    return () => document.removeEventListener("click", onDocClick)
  }, [open])

  const expectedOptions =
    kind === "tone" ? toneOptions : kind === "style" ? styleOptions : []
  const predicted =
    kind === "tone"
      ? row.tone_predicted
      : kind === "style"
        ? row.style_predicted
        : null

  async function handleSubmit() {
    if (!kind || !expected || !predicted) return
    setBusy(true)
    setError(null)
    try {
      await createRunMisclassificationFlag(runId, {
        text: row.text,
        predicted_label: predicted,
        expected_label: expected,
        kind,
        source_type: row.source_type,
        source_ref: row.source_ref,
        attempt_id: attemptId,
        variant_id: variantId,
        locale: locale === "en" ? "en" : "sv",
      })
      onReported()
      setPicking(false)
      setKind("")
      setExpected("")
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("runs.results.misclassification.error"),
      )
    } finally {
      setBusy(false)
    }
  }

  function startReport(event: MouseEvent) {
    event.stopPropagation()
    if (reported) return
    const nextKind = availableKinds.length === 1 ? availableKinds[0] : ""
    setKind(nextKind)
    setExpected("")
    setError(null)
    setPicking(true)
  }

  return (
    <div className="class-pop" ref={rootRef}>
      <button
        type="button"
        className={"results-icon-btn" + (open ? " on" : "")}
        title={t("runs.results.anchorPool.showClassification")}
        aria-label={t("runs.results.anchorPool.showClassification")}
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation()
          setOpen((prev) => !prev)
        }}
      >
        <StarIcon />
      </button>
      {open ? (
        <div
          className="class-pop-panel"
          role="dialog"
          aria-label={t("runs.results.anchorPool.systemClassification")}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="class-pop-kicker">
            {t("runs.results.anchorPool.systemClassification")}
          </div>
          <div className="class-pop-pills">
            {row.tone_predicted ? (
              <span title={t("runs.results.anchorPool.classToneTitle")}>
                {row.tone_predicted}
              </span>
            ) : null}
            {row.style_predicted ? (
              <span title={t("runs.results.anchorPool.classStyleTitle")}>
                {row.style_predicted}
              </span>
            ) : null}
          </div>
          {picking && !reported ? (
            <>
              {availableKinds.length > 1 ? (
                <div className="class-pop-fields">
                  <select
                    value={kind}
                    disabled={busy}
                    onChange={(event) => {
                      setKind(event.target.value as FlagKind | "")
                      setExpected("")
                    }}
                  >
                    <option value="">{t("runs.results.anchorPool.none")}</option>
                    {availableKinds.map((item) => (
                      <option key={item} value={item}>
                        {item === "tone"
                          ? t("runs.results.misclassification.kindTone")
                          : t("runs.results.misclassification.kindStyle")}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              {kind ? (
                <div className="class-pop-fields">
                  <select
                    value={expected}
                    disabled={busy}
                    onChange={(event) => setExpected(event.target.value)}
                  >
                    <option value="">
                      {t("runs.results.misclassification.pickExpected")}
                    </option>
                    {expectedOptions
                      .filter((label) => label !== predicted)
                      .map((label) => (
                        <option key={label} value={label}>
                          {label}
                        </option>
                      ))}
                  </select>
                </div>
              ) : null}
              {error ? <p className="class-pop-error">{error}</p> : null}
              <button
                type="button"
                className="class-pop-report"
                disabled={busy || !kind || !expected}
                onClick={() => void handleSubmit()}
              >
                {busy
                  ? t("runs.results.misclassification.submitting")
                  : t("runs.results.misclassification.submit")}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="class-pop-report"
              disabled={reported || availableKinds.length === 0}
              onClick={startReport}
            >
              {reported
                ? t("runs.results.misclassification.reported")
                : t("runs.results.misclassification.report")}
            </button>
          )}
        </div>
      ) : null}
    </div>
  )
}

export function flaggedKeyForRow(row: RunTaggableTextRow): string {
  return `${row.source_type}-${sourceRefKey(row.source_ref)}`
}
