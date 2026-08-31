import { useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import {
  chatDdSourcing,
  mergeDdCandidates,
  updateDdCampaign,
  type DdCampaign,
  type DdCandidateCompany,
  type DdSourcingChatMessage,
} from "@/api/dd"
import { MessengerChat, type MessengerChatMessage } from "@/components/chat/MessengerChat"
import { DdCandidateFacts } from "@/components/dd/DdCandidateFacts"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

function existingOrgnrs(campaign: DdCampaign): Set<string> {
  return new Set(campaign.candidates.map((c) => c.organisationsnummer))
}

function briefFromHistory(history: DdSourcingChatMessage[]): string {
  return history
    .filter((row) => row.role === "user")
    .map((row) => row.content.trim())
    .filter(Boolean)
    .join(" · ")
}

export function DdSourcingSearchModal({
  open,
  campaign,
  onClose,
  onAdded,
}: {
  open: boolean
  campaign: DdCampaign
  onClose: () => void
  onAdded: (next: DdCampaign) => void
}) {
  const { t } = useLocale()
  const overlayMouseDownRef = useRef(false)
  const nextId = useRef(1)
  const [messages, setMessages] = useState<MessengerChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [results, setResults] = useState<DdCandidateCompany[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    nextId.current = 1
    setMessages([])
    setDraft("")
    setResults([])
    setSelectedIds([])
    setBusy(false)
    setAdding(false)
    setError(null)
  }, [open])

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
      if (e.key === "Escape" && !adding && !busy) onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, adding, busy, onClose])

  const inCampaign = useMemo(() => existingOrgnrs(campaign), [campaign])
  const selectableResults = useMemo(
    () => results.filter((c) => !inCampaign.has(c.organisationsnummer)),
    [inCampaign, results],
  )
  const selectedSelectable = useMemo(
    () => selectableResults.filter((c) => selectedIds.includes(c.id)),
    [selectableResults, selectedIds],
  )
  const allNewSelected =
    selectableResults.length > 0 && selectedSelectable.length === selectableResults.length
  const history: DdSourcingChatMessage[] = messages.map((row) => ({
    role: row.role,
    content: row.content,
  }))

  async function sendText(text: string) {
    const trimmed = text.trim()
    if (!trimmed || busy || adding) return
    const userMsg: MessengerChatMessage = { id: nextId.current, role: "user", content: trimmed }
    nextId.current += 1
    setDraft("")
    setMessages((prev) => [...prev, userMsg])
    setError(null)
    setBusy(true)
    try {
      const { reply, candidates } = await chatDdSourcing(campaign.id, {
        message: trimmed,
        history,
      })
      setMessages((prev) => [
        ...prev,
        { id: nextId.current, role: "assistant", content: reply },
      ])
      nextId.current += 1
      setResults((prev) => mergeDdCandidates(prev, candidates))
    } catch (err: unknown) {
      const fallback = t("dd.sourcing.chatError")
      setError(
        err instanceof ApiError && !err.message.includes("invalid reply")
          ? err.message
          : fallback,
      )
    } finally {
      setBusy(false)
    }
  }

  function onSend() {
    void sendText(draft)
  }

  function toggleResult(candidate: DdCandidateCompany) {
    if (inCampaign.has(candidate.organisationsnummer)) return
    setSelectedIds((prev) =>
      prev.includes(candidate.id) ? prev.filter((id) => id !== candidate.id) : [...prev, candidate.id],
    )
  }

  function selectAllNew() {
    setSelectedIds(selectableResults.map((c) => c.id))
  }

  function deselectAll() {
    setSelectedIds([])
  }

  async function onAddSelected() {
    const picked = results.filter((c) => selectedIds.includes(c.id) && !inCampaign.has(c.organisationsnummer))
    if (picked.length === 0) {
      setError(t("dd.sourcing.noSelection"))
      return
    }
    setError(null)
    setAdding(true)
    try {
      const brief = campaign.criteria.fritext.trim() || briefFromHistory(history)
      const merged = mergeDdCandidates(campaign.candidates, picked)
      const next = await updateDdCampaign(campaign.id, {
        criteria: { ...campaign.criteria, fritext: brief || campaign.criteria.fritext },
        candidates: merged,
        selected_candidate_ids: merged.map((c) => c.id),
        status: campaign.status === "draft" ? "sourcing" : campaign.status,
        enrich_from_allabolag: true,
      })
      onAdded(next)
      onClose()
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.sourcing.addError"))
    } finally {
      setAdding(false)
    }
  }

  if (!open) return null

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current && !adding && !busy) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div
        className="flex h-[min(90vh,52rem)] max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dd-sourcing-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[color:var(--border-hairline)] px-5 py-4">
          <h2 id="dd-sourcing-modal-title" className="text-base font-medium text-foreground">
            {t("dd.sourcing.modalTitle")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("dd.sourcing.modalIntro")}</p>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-5 py-4">
          {error ? (
            <p className="shrink-0 text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}

          <div
            className={`grid min-h-0 flex-1 gap-4 overflow-hidden ${
              results.length > 0 ? "grid-cols-[minmax(0,1fr)_minmax(13rem,16rem)]" : "grid-cols-1"
            }`}
          >
          <div className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-md border border-[color:var(--border-hairline)]">
            <MessengerChat
              className="h-full min-h-0"
              messages={messages}
              draft={draft}
              onDraftChange={setDraft}
              onSend={onSend}
              busy={busy}
              typing={busy}
              disabled={adding}
              placeholder={t("dd.sourcing.chatPlaceholder")}
              empty={<p className="text-sm text-muted-foreground">{t("dd.sourcing.chatEmpty")}</p>}
              suggestions={messages.length === 0 ? [
                t("dd.sourcing.chatSuggestionIt"),
                t("dd.sourcing.chatSuggestionGbg"),
              ] : []}
              onSuggestion={(question) => {
                void sendText(question)
              }}
            />
          </div>

          {results.length > 0 ? (
            <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">
              <div className="mb-3 flex shrink-0 flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium">
                  {t("dd.sourcing.resultsCount", { count: results.length })}
                </h3>
                {selectableResults.length > 0 ? (
                  <AdminButton
                    variant="secondary"
                    size="sm"
                    disabled={adding}
                    onClick={allNewSelected ? deselectAll : selectAllNew}
                  >
                    {t(allNewSelected ? "dd.sourcing.deselectAll" : "dd.sourcing.selectAll")}
                  </AdminButton>
                ) : null}
              </div>
              <ul className="grid min-h-0 flex-1 content-start gap-2 overflow-y-auto">
                {results.map((candidate) => {
                  const alreadyIn = inCampaign.has(candidate.organisationsnummer)
                  const checked = !alreadyIn && selectedIds.includes(candidate.id)
                  return (
                    <li key={candidate.id}>
                      <label
                        className={`flex cursor-pointer gap-3 rounded-md border border-[color:var(--border-hairline)] p-2.5 ${
                          alreadyIn ? "cursor-default opacity-70" : ""
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={checked}
                          disabled={alreadyIn || adding}
                          aria-label={t("dd.sourcing.selectCandidate", { name: candidate.namn })}
                          onChange={() => toggleResult(candidate)}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <span className="font-medium">{candidate.namn}</span>
                            <span className="text-xs text-muted-foreground">
                              {candidate.organisationsnummer}
                            </span>
                          </div>
                          {candidate.beskrivning ? (
                            <p className="mt-1 text-sm text-muted-foreground">{candidate.beskrivning}</p>
                          ) : null}
                          <div className="mt-2">
                            <DdCandidateFacts candidate={candidate} compact />
                          </div>
                          {alreadyIn ? (
                            <p className="mt-2 text-xs text-muted-foreground">
                              {t("dd.sourcing.alreadyInCampaign")}
                            </p>
                          ) : null}
                        </div>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-[color:var(--border-hairline)] px-5 py-4">
          <AdminButton variant="secondary" disabled={adding} onClick={onClose}>
            {t("common.cancel")}
          </AdminButton>
          <AdminButton
            disabled={adding || selectedIds.length === 0}
            onClick={() => void onAddSelected()}
          >
            {adding ? t("dd.sourcing.adding") : t("dd.sourcing.addSelected", { count: selectedIds.length })}
          </AdminButton>
        </div>
      </div>
    </div>,
    document.body,
  )
}
