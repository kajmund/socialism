import { useState } from "react"
import { createPortal } from "react-dom"
import {
  addRunAnchorPoolItems,
  type RunTaggableTextRow,
} from "@/api/runs"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export type AddAnchorTarget = {
  row: RunTaggableTextRow
  author: string
}

type Props = {
  open: boolean
  target: AddAnchorTarget | null
  runId: number
  attemptId: string
  variantId: string
  toneName: string
  styleName: string
  toneOptions: string[]
  styleOptions: string[]
  onClose: () => void
  onAdded: () => void
}

export function AddAnchorModal({
  open,
  target,
  runId,
  attemptId,
  variantId,
  toneName,
  styleName,
  toneOptions,
  styleOptions,
  onClose,
  onAdded,
}: Props) {
  const { locale, t } = useLocale()
  const [tone, setTone] = useState("")
  const [style, setStyle] = useState("")
  const [addToCalibration, setAddToCalibration] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open || !target) return null

  const current = target
  const canAdd = Boolean(tone || style)
  const hasClassification = Boolean(
    current.row.tone_predicted || current.row.style_predicted,
  )

  async function handleAdd() {
    if (!canAdd) return
    setBusy(true)
    setError(null)
    try {
      await addRunAnchorPoolItems(runId, {
        text: current.row.text,
        source_type: current.row.source_type,
        source_ref: current.row.source_ref,
        attempt_id: attemptId,
        variant_id: variantId,
        tone_label: tone || null,
        style_label: style || null,
        add_to_calibration: addToCalibration,
        locale,
      })
      setTone("")
      setStyle("")
      setAddToCalibration(false)
      onAdded()
      onClose()
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("runs.results.anchorPool.addError"),
      )
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div
      className="theme-admin results-modal-overlay"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="results-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-anchor-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="results-modal-head">
          <h3 id="add-anchor-title">{t("runs.results.anchorPool.addModalTitle")}</h3>
          <div className="results-set-pills">
            <span title={t("runs.results.anchorPool.activeSetToneTitle")}>
              {toneName}
            </span>
            <span title={t("runs.results.anchorPool.activeSetStyleTitle")}>
              {styleName}
            </span>
          </div>
        </div>

        <div className="results-modal-quote">
          <div className="results-modal-quote-meta">
            {t("runs.results.anchorPool.commentAuthor", { author: current.author })}
          </div>
          <p>{current.row.text}</p>
          {hasClassification ? (
            <>
              <div className="results-modal-class-lbl">
                {t("runs.results.anchorPool.systemClassification")}
              </div>
              <div className="results-class-pills">
                <StarIcon size={11} />
                {current.row.tone_predicted ? (
                  <span title={t("runs.results.anchorPool.classToneTitle")}>
                    {current.row.tone_predicted}
                  </span>
                ) : null}
                {current.row.style_predicted ? (
                  <span title={t("runs.results.anchorPool.classStyleTitle")}>
                    {current.row.style_predicted}
                  </span>
                ) : null}
              </div>
            </>
          ) : null}
        </div>

        <div className="results-modal-fields">
          <label>
            <span>{t("runs.results.anchorPool.toneLabel")}</span>
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              disabled={busy}
            >
              <option value="">{t("runs.results.anchorPool.none")}</option>
              {toneOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("runs.results.anchorPool.styleLabel")}</span>
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              disabled={busy}
            >
              <option value="">{t("runs.results.anchorPool.none")}</option>
              {styleOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="results-modal-check">
          <input
            type="checkbox"
            checked={addToCalibration}
            disabled={busy}
            onChange={(e) => setAddToCalibration(e.target.checked)}
          />
          {t("runs.results.anchorPool.addCalibration")}
        </label>

        {error ? <p className="results-modal-error">{error}</p> : null}

        <div className="results-modal-actions">
          <button type="button" className="results-modal-cancel" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="results-modal-add"
            disabled={!canAdd || busy}
            onClick={() => void handleAdd()}
          >
            {busy
              ? t("runs.results.anchorPool.adding")
              : t("runs.results.anchorPool.addConfirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function StarIcon({ size = 13 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 3l1.9 4.9L19 9.8l-4.9 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9L12 3z" />
    </svg>
  )
}

export function ShieldIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 22s8-4.5 8-11V5l-8-3-8 3v6c0 6.5 8 11 8 11z" />
    </svg>
  )
}
