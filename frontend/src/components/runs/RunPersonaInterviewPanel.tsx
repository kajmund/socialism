import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { RunInterviewChat } from "@/components/runs/RunInterviewChat"
import { AdminButton } from "@/components/ui/admin-button"
import type { OasisVariantResult } from "@/data/runs-types"
import { useLocale } from "@/i18n"

type ModalProps = {
  open: boolean
  onClose: () => void
  runId: number
  attemptId: string
  variant: OasisVariantResult
  tickIndex: number
  initialPersonaId?: string | null
}

export function RunPersonaInterviewModal({
  open,
  onClose,
  runId,
  attemptId,
  variant,
  tickIndex,
  initialPersonaId = null,
}: ModalProps) {
  const { t } = useLocale()
  const overlayMouseDownRef = useRef(false)
  const day = variant.tick_markers?.[tickIndex]?.day ?? tickIndex + 1

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="run-interview-modal-title"
      onMouseDown={(event) => {
        overlayMouseDownRef.current = event.target === event.currentTarget
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div className="flex max-h-[min(880px,92vh)] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <div>
            <h2 id="run-interview-modal-title" className="text-base font-medium">
              {t("runs.interview.modalTitle", { day })}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("runs.interview.modalDescription")}
            </p>
          </div>
          <button
            type="button"
            className="tl-icon-btn shrink-0 text-lg"
            onClick={onClose}
            aria-label={t("common.close")}
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <RunInterviewChat
            runId={runId}
            attemptId={attemptId}
            variant={variant}
            tickIndex={tickIndex}
            initialPersonaId={initialPersonaId}
          />
        </div>
        <div className="flex justify-end gap-2 border-t border-[color:var(--border-hairline)] px-5 py-4">
          <AdminButton variant="primary" onClick={onClose}>
            {t("common.done")}
          </AdminButton>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function InterviewIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

export { InterviewIcon }

/** @deprecated Prefer RunPersonaInterviewModal opened from a day row. */
export function RunPersonaInterviewPanel(props: {
  runId: number
  attemptId: string
  variant: OasisVariantResult
  initialTickIndex?: number
}) {
  const { t } = useLocale()
  const [tickIndex, setTickIndex] = useState(props.initialTickIndex ?? 0)
  return (
    <section className="mt-6 rounded-md border border-[color:var(--border-hairline)] p-4">
      <h3 className="mb-1 text-sm font-medium text-foreground">
        {t("runs.interview.panelTitle")}
      </h3>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("runs.interview.panelDescription")}
      </p>
      <RunInterviewChat
        runId={props.runId}
        attemptId={props.attemptId}
        variant={props.variant}
        tickIndex={tickIndex}
        onTickIndexChange={setTickIndex}
        showTickSelect
      />
    </section>
  )
}
