import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import {
  clearRunPersonaInterview,
  listRunPersonaInterviewMessages,
  runPersonaInterview,
  type RunInterviewMessage,
} from "@/api/runs"
import { AdminButton } from "@/components/ui/admin-button"
import { ApiError } from "@/lib/api"
import type { OasisVariantResult } from "@/data/runs-types"

type PanelBodyProps = {
  runId: number
  attemptId: string
  variant: OasisVariantResult
  tickIndex: number
  onTickIndexChange?: (index: number) => void
  showTickSelect?: boolean
  initialPersonaId?: string | null
}

function InterviewBody({
  runId,
  attemptId,
  variant,
  tickIndex,
  onTickIndexChange,
  showTickSelect = false,
  initialPersonaId = null,
}: PanelBodyProps) {
  const markers = variant.tick_markers ?? []
  const populationAgents = useMemo(
    () =>
      (variant.agents ?? []).filter(
        (a) => a.role !== "injector" && Boolean(a.persona_id),
      ),
    [variant.agents],
  )

  const [personaId, setPersonaId] = useState("")
  const [messages, setMessages] = useState<RunInterviewMessage[]>([])
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (populationAgents.length === 0) return
    if (
      initialPersonaId &&
      populationAgents.some((a) => a.persona_id === initialPersonaId)
    ) {
      setPersonaId(initialPersonaId)
      return
    }
    setPersonaId((prev) => {
      if (prev && populationAgents.some((a) => a.persona_id === prev)) return prev
      return populationAgents[0]!.persona_id!
    })
  }, [populationAgents, initialPersonaId])

  const loadMessages = useCallback(async () => {
    if (!personaId || markers.length === 0) {
      setMessages([])
      return
    }
    setError(null)
    try {
      const rows = await listRunPersonaInterviewMessages(
        runId,
        attemptId,
        variant.id,
        personaId,
        tickIndex,
      )
      setMessages(rows)
    } catch (err) {
      setMessages([])
      setError(err instanceof ApiError ? err.message : "Kunde inte hämta intervju")
    }
  }, [runId, attemptId, variant.id, personaId, tickIndex, markers.length])

  useEffect(() => {
    void loadMessages()
  }, [loadMessages])

  async function send() {
    const trimmed = draft.trim()
    if (!trimmed || !personaId || busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await runPersonaInterview(
        runId,
        attemptId,
        variant.id,
        personaId,
        { through_tick_index: tickIndex, message: trimmed },
      )
      setMessages(result.messages)
      setDraft("")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Intervjun misslyckades")
    } finally {
      setBusy(false)
    }
  }

  async function clearThread() {
    if (!personaId || busy) return
    setBusy(true)
    setError(null)
    try {
      await clearRunPersonaInterview(
        runId,
        attemptId,
        variant.id,
        personaId,
        tickIndex,
      )
      setMessages([])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunde inte rensa")
    } finally {
      setBusy(false)
    }
  }

  if (populationAgents.length === 0 || markers.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Ingen population eller tick-markörer att intervjua från.
      </p>
    )
  }

  const day = markers[tickIndex]?.day ?? tickIndex + 1

  return (
    <div>
      <div
        className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-foreground"
        role="status"
      >
        Intervju efter dag {day} (tick {tickIndex + 1}) — persona ser inte dag{" "}
        {day + 1}+
      </div>

      <div className="mb-3 flex flex-wrap gap-3">
        <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-xs text-muted-foreground">
          Persona
          <select
            className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-foreground"
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value)}
          >
            {populationAgents.map((a) => (
              <option key={a.persona_id!} value={a.persona_id!}>
                {a.member_name}
              </option>
            ))}
          </select>
        </label>
        {showTickSelect ? (
          <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs text-muted-foreground">
            Efter tick
            <select
              className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-foreground"
              value={tickIndex}
              onChange={(e) => onTickIndexChange?.(Number(e.target.value))}
            >
              {markers.map((m) => (
                <option key={m.key || m.tick_index} value={m.tick_index}>
                  Dag {m.day} (tick {m.tick_index + 1})
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <div className="mb-3 max-h-64 space-y-2 overflow-y-auto rounded border border-[color:var(--border-hairline)] bg-black/10 p-3">
        {messages.length === 0 ? (
          <p className="text-xs text-muted-foreground">Ingen intervju ännu.</p>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={
                m.role === "user"
                  ? "text-sm text-foreground"
                  : "text-sm text-muted-foreground"
              }
            >
              <span className="mr-2 text-xs font-medium uppercase tracking-wide opacity-70">
                {m.role === "user" ? "Du" : "Persona"}
              </span>
              {m.content}
            </div>
          ))
        )}
      </div>

      {error ? (
        <p className="mb-2 text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-col gap-2 sm:flex-row">
        <textarea
          className="min-h-[4rem] flex-1 rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm"
          placeholder="Ställ en fråga…"
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
        />
        <div className="flex flex-col gap-2">
          <AdminButton
            type="button"
            disabled={busy || !draft.trim()}
            onClick={() => void send()}
          >
            Skicka
          </AdminButton>
          <AdminButton
            type="button"
            variant="secondary"
            disabled={busy || messages.length === 0}
            onClick={() => void clearThread()}
          >
            Rensa
          </AdminButton>
        </div>
      </div>
    </div>
  )
}

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
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
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
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div className="flex max-h-[min(880px,92vh)] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <div>
            <h2 id="run-interview-modal-title" className="text-base font-medium">
              Intervju efter dag {day}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Fri chat med flödeskontext fram till denna tick — inte framtida
              dagar.
            </p>
          </div>
          <button
            type="button"
            className="tl-icon-btn shrink-0 text-lg"
            onClick={onClose}
            aria-label="Stäng"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <InterviewBody
            runId={runId}
            attemptId={attemptId}
            variant={variant}
            tickIndex={tickIndex}
            initialPersonaId={initialPersonaId}
          />
        </div>
        <div className="flex justify-end gap-2 border-t border-[color:var(--border-hairline)] px-5 py-4">
          <AdminButton variant="primary" onClick={onClose}>
            Klar
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
  const [tickIndex, setTickIndex] = useState(props.initialTickIndex ?? 0)
  return (
    <section className="mt-6 rounded-md border border-[color:var(--border-hairline)] p-4">
      <h3 className="mb-1 text-sm font-medium text-foreground">
        Post-hoc intervju
      </h3>
      <p className="mb-3 text-xs text-muted-foreground">
        Fri chat efter körningen. Persona får bara flödeskontext fram till vald
        tick — inte framtida dagar.
      </p>
      <InterviewBody
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
