import { actionCardModel } from "@/lib/actionQueue"
import type { WordAction } from "@/lib/types"
import type { MessageKey } from "@/i18n/messages"

type ActionCardProps = {
  action: WordAction
  busy: boolean
  onApply: (action: WordAction) => void
  onDismiss: (action: WordAction) => void
  t: (key: MessageKey, params?: Record<string, string | number>) => string
}

function statusLabel(
  status: string,
  t: ActionCardProps["t"],
): string | null {
  switch (status) {
    case "applied":
      return t("actionApplied")
    case "dismissed":
      return t("actionDismissed")
    case "applying":
      return t("actionApplying")
    default:
      return null
  }
}

function unresolvedReasonLabel(
  reason: NonNullable<ReturnType<typeof actionCardModel>["unresolvedReason"]>,
  t: ActionCardProps["t"],
): string {
  switch (reason) {
    case "stale":
      return t("unresolvedStale")
    case "ambiguous":
      return t("unresolvedAmbiguous")
    case "missing":
      return t("unresolvedMissing")
    case "unsupported_action":
      return t("unresolvedUnsupported")
    case "unknown":
      return t("unresolvedUnknown")
    default: {
      const _exhaustive: never = reason
      return _exhaustive
    }
  }
}

export function ActionCard({ action, busy, onApply, onDismiss, t }: ActionCardProps) {
  const model = actionCardModel(action)
  const titleKey: MessageKey =
    model.kind === "replace" ? "actionReplace" : "actionComment"
  const label = statusLabel(model.status, t)
  return (
    <article
      className="action-card"
      data-status={model.status}
      data-deemphasized={model.deemphasized ? "true" : "false"}
      data-action-id={action.id}
    >
      <header className="action-card-head">
        <h3>{t(titleKey)}</h3>
        {label ? <p className="action-card-status">{label}</p> : null}
      </header>
      {model.kind === "replace" ? (
        <div className="action-card-fields">
          <div>
            <p className="action-card-label">{t("actionCurrent")}</p>
            <p className="action-card-text">{model.reviewedText}</p>
          </div>
          <div>
            <p className="action-card-label">{t("actionSuggested")}</p>
            <p className="action-card-text">{model.content}</p>
          </div>
          {model.explanation ? (
            <div>
              <p className="action-card-label">{t("actionWhy")}</p>
              <p className="action-card-text">{model.explanation}</p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="action-card-fields">
          <p className="action-card-text">{model.content}</p>
          {model.explanation ? (
            <details className="action-card-why">
              <summary>{t("actionWhyMore")}</summary>
              <p className="action-card-text">{model.explanation}</p>
            </details>
          ) : null}
        </div>
      )}
      {model.unresolvedReason ? (
        <p className="action-card-unresolved" data-unresolved-reason={model.unresolvedReason}>
          {unresolvedReasonLabel(model.unresolvedReason, t)}
        </p>
      ) : null}
      {model.showApplying ? (
        <p className="action-card-uncertain">{t("actionApplyingHint")}</p>
      ) : null}
      {model.showApply || model.showDismiss ? (
        <div className="action-card-actions">
          {model.showApply ? (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => onApply(action)}
            >
              {t("actionApply")}
            </button>
          ) : null}
          {model.showDismiss ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => onDismiss(action)}
            >
              {t("actionDismiss")}
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}
