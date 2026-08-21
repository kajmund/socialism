import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import {
  catalogToFieldOptions,
  listCatalog,
} from "@/api/catalog"
import {
  chatWithPersona,
  clearPersonaMessages,
  createPersona,
  deletePersona,
  deletePersonaMessage,
  duplicatePersona,
  editableToWrite,
  generatePersonas,
  getPersona,
  getSuggestedQuestions,
  listPersonaMessages,
  resendPersonaMessage,
  updatePersona,
  type ChatMode,
  type PersonaMessage,
} from "@/api/personas"
import { ChatMessageActions } from "@/components/chat/ChatMessageActions"
import { MessengerChat } from "@/components/chat/MessengerChat"
import {
  doneToPersonaMessages,
  useChatSocket,
} from "@/components/chat/useChatSocket"
import { AdminShell } from "@/components/layout/AdminShell"
import { PersonaAnekdotEditor, PersonaAnekdotPresentation } from "@/components/personas/PersonaAnekdot"
import { PersonaLibrarySaveAction } from "@/components/personas/PersonaLibrarySaveAction"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { blankEditablePersona } from "@/data/library"
import type { EditablePersona, PersonaOrigin } from "@/data/library-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

type LayerRow = { k: keyof EditablePersona | string; l: string; v: string; locked: boolean }

function ConfirmModal({
  open,
  titleId,
  title,
  description,
  children,
  onClose,
}: {
  open: boolean
  titleId: string
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
}) {
  const overlayMouseDownRef = useRef(false)

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
      aria-labelledby={titleId}
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
      <div
        className="w-full max-w-md rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[color:var(--border-hairline)] px-5 py-4">
          <h2 id={titleId} className="text-base font-medium text-foreground">
            {title}
          </h2>
          {description ? (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

type LayerTableProps = {
  rows: LayerRow[]
  pol?: boolean
  fieldOptions: Record<string, string[]>
  t: Translate
  onChange: (k: string, v?: string) => void
}

function LayerTable({ rows, pol, fieldOptions, t, onChange }: LayerTableProps) {
  return (
    <table className={"lt" + (pol ? " pol" : "")}>
      <tbody>
        {rows.map((r) => {
          const opts = fieldOptions[r.k]
          // Lock marks fields for regeneration — it must not block editing.
          const cell =
            opts && opts.length > 0 ? (
              <select
                className="cell-input"
                value={r.v}
                onChange={(e) => onChange(r.k, e.target.value)}
              >
                {!opts.includes(r.v) && (
                  <option value={r.v}>{r.v || "—"}</option>
                )}
                {opts.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="cell-input"
                value={r.v}
                onChange={(e) => onChange(r.k, e.target.value)}
              />
            )
          return (
            <tr key={r.k}>
              <td className="k">{r.l}</td>
              <td>{cell}</td>
              <td className="lk">
                <span
                  className={"lock" + (r.locked ? " on" : "")}
                  onClick={() => onChange("__lock__" + r.k)}
                  title={
                    r.locked
                      ? t("personas.composer.lockedRegenerate")
                      : t("personas.composer.unlockedRegenerate")
                  }
                >
                  {r.locked ? "🔒" : "🔓"}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

type EditorProps = {
  persona: EditablePersona
  personaId: string | null
  personaOrigin: PersonaOrigin
  onLibraryOriginChange: (origin: PersonaOrigin) => void
  t: Translate
  setPersona: (updater: (p: EditablePersona) => EditablePersona) => void
  onOpenVariants: () => void
  onDuplicate: () => void
  onSave: () => void
  onDelete?: () => void
  onToast: (message: string) => void
  fieldOptions: Record<string, string[]>
  saving?: boolean
  deleting?: boolean
}

function Editor({
  persona,
  personaId,
  personaOrigin,
  onLibraryOriginChange,
  t,
  setPersona,
  onOpenVariants,
  onDuplicate,
  onSave,
  onDelete,
  onToast,
  fieldOptions,
  saving,
  deleting,
}: EditorProps) {
  const [mode, setMode] = useState<"work" | "present">("work")
  const [icMode, setIcMode] = useState<ChatMode>("interview")
  const [saved, setSaved] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [locks, setLocks] = useState<Record<string, boolean>>({
    age: true,
    ort: true,
    lutning: true,
    parti: true,
    valdeltagande: true,
  })
  const [messages, setMessages] = useState<PersonaMessage[]>([])
  const [optimisticUser, setOptimisticUser] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [restBusy, setRestBusy] = useState(false)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const suggestGen = useRef(0)
  const [confirmClearInterview, setConfirmClearInterview] = useState(false)
  const [confirmDeleteMessageId, setConfirmDeleteMessageId] = useState<number | null>(
    null,
  )
  const chatHello = useMemo(
    () =>
      personaId
        ? ({ scope: "library" as const, persona_id: personaId, mode: icMode })
        : null,
    [personaId, icMode],
  )

  const {
    ready: chatReady,
    busy: socketBusy,
    typing: chatTyping,
    streamText,
    send: socketSend,
  } = useChatSocket({
    hello: chatHello,
    onDone: (rows) => {
      setMessages(doneToPersonaMessages(rows, icMode))
      setOptimisticUser(null)
    },
    onSuggestions: (questions) => {
      setSuggestions(questions)
    },
    onError: (detail) => {
      setOptimisticUser(null)
      onToast(detail || t("personas.composer.sendError"))
    },
  })

  const chatBusy = restBusy || socketBusy

  useEffect(() => {
    if (!personaId) {
      setMessages([])
      setOptimisticUser(null)
      setSuggestions([])
      return
    }
    if (!chatReady) {
      setOptimisticUser(null)
      return
    }
    let cancelled = false
    const gen = ++suggestGen.current
    listPersonaMessages(personaId, icMode)
      .then((rows) => {
        if (!cancelled) {
          setMessages(rows)
          setOptimisticUser(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          onToast(err instanceof ApiError ? err.message : t("personas.composer.fetchChatError"))
        }
      })
    getSuggestedQuestions(personaId, icMode)
      .then((res) => {
        if (!cancelled && gen === suggestGen.current) {
          setSuggestions(res.questions)
        }
      })
      .catch(() => {
        if (!cancelled && gen === suggestGen.current) {
          setSuggestions([])
        }
      })
    return () => {
      cancelled = true
    }
    // intentionally omit onToast/t — parent recreates them each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personaId, icMode, chatReady])

  function sendMessage(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !personaId || chatBusy) return
    suggestGen.current += 1
    setSuggestions([])
    setOptimisticUser(trimmed)
    setDraft("")
    if (!socketSend(trimmed)) {
      setOptimisticUser(null)
      setDraft(trimmed)
      onToast(t("chat.notConnected"))
    }
  }

  async function regenerate() {
    if (!personaId || chatBusy) return
    const lastUser = [...messages].reverse().find((m) => m.role === "user")
    setRestBusy(true)
    try {
      await clearPersonaMessages(personaId, icMode)
      if (lastUser) {
        const result = await chatWithPersona(personaId, {
          mode: icMode,
          message: lastUser.content,
        })
        setMessages(result.messages)
        setSuggestions(result.suggestions ?? [])
      } else {
        setMessages([])
        setSuggestions([])
      }
      setOptimisticUser(null)
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : t("personas.composer.regenerateError"))
    } finally {
      setRestBusy(false)
    }
  }

  async function confirmClearInterviewAction() {
    if (!personaId || chatBusy || messages.length === 0) return
    setRestBusy(true)
    try {
      await clearPersonaMessages(personaId, icMode)
      setMessages([])
      setDraft("")
      setOptimisticUser(null)
      setConfirmClearInterview(false)
      const gen = ++suggestGen.current
      try {
        const res = await getSuggestedQuestions(personaId, icMode)
        if (gen === suggestGen.current) setSuggestions(res.questions)
      } catch {
        if (gen === suggestGen.current) setSuggestions([])
      }
    } catch (err) {
      onToast(
        err instanceof ApiError
          ? err.message
          : icMode === "interview"
            ? t("personas.composer.clearInterviewError")
            : t("personas.composer.clearChatError"),
      )
    } finally {
      setRestBusy(false)
    }
  }

  const clearChatLabel =
    icMode === "interview"
      ? t("personas.composer.clearInterview")
      : t("personas.composer.clearChat")
  const clearConfirmTitle =
    icMode === "interview"
      ? t("personas.composer.clearInterviewConfirmTitle")
      : t("personas.composer.clearChatConfirmTitle")
  const clearConfirmDescription =
    icMode === "interview"
      ? t("personas.composer.clearInterviewConfirmDesc")
      : t("personas.composer.clearChatConfirmDesc")

  async function confirmDeleteMessageAction() {
    if (!personaId || chatBusy || confirmDeleteMessageId == null) return
    const targetId = confirmDeleteMessageId
    setRestBusy(true)
    try {
      const result = await deletePersonaMessage(personaId, targetId)
      const removed = new Set(result.deleted_ids)
      setMessages((prev) => prev.filter((m) => !removed.has(m.id)))
      setConfirmDeleteMessageId(null)
    } catch (err) {
      // Paired delete already removed this id server-side while the bubble lingered.
      if (err instanceof ApiError && err.status === 404) {
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === targetId)
          if (idx < 0) return prev
          const target = prev[idx]!
          const drop = new Set<number>([targetId])
          if (target.role === "user" && prev[idx + 1]?.role === "assistant") {
            drop.add(prev[idx + 1]!.id)
          } else if (target.role === "assistant" && idx > 0 && prev[idx - 1]?.role === "user") {
            drop.add(prev[idx - 1]!.id)
          }
          return prev.filter((m) => !drop.has(m.id))
        })
        setConfirmDeleteMessageId(null)
        try {
          setMessages(await listPersonaMessages(personaId, icMode))
        } catch {
          // local heal above is enough
        }
      } else {
        onToast(
          err instanceof ApiError ? err.message : t("personas.composer.deleteMessageError"),
        )
      }
    } finally {
      setRestBusy(false)
    }
  }

  const messagePendingDelete = messages.find((m) => m.id === confirmDeleteMessageId)

  async function resendMessage(messageId: number) {
    if (!personaId || chatBusy) return
    setRestBusy(true)
    try {
      const result = await resendPersonaMessage(personaId, messageId)
      setMessages(result.messages)
      setOptimisticUser(null)
      setSuggestions(result.suggestions ?? [])
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : t("personas.composer.resendError"))
    } finally {
      setRestBusy(false)
    }
  }

  function upd(k: string, v?: string) {
    if (k.startsWith("__lock__")) {
      const field = k.slice("__lock__".length)
      setLocks((prev) => ({ ...prev, [field]: !prev[field] }))
      return
    }
    setPersona((p) => {
      const next = { ...p, [k]: v ?? "" }
      if (k === "name") {
        const parts = next.name.split(" ")
        next.initials = (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")
        next.initials = next.initials.toUpperCase() || "--"
      }
      return next
    })
  }

  return (
    <>
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="topbar">
        <div className="persona-id">
          <div className="avatar">{persona.initials}</div>
          <div>
            <input
              className="nm-input"
              value={persona.name}
              onChange={(e) => upd("name", e.target.value)}
            />
            <div className="sub">
              {persona.age} · {persona.yrke} · {persona.ort}
            </div>
          </div>
        </div>
        <div className="topbar-actions">
          <div className="mode-switch">
            <button
              type="button"
              className={mode === "work" ? "on" : ""}
              onClick={() => setMode("work")}
            >
              {t("personas.composer.workMode")}
            </button>
            <button
              type="button"
              className={mode === "present" ? "on" : ""}
              onClick={() => setMode("present")}
            >
              {t("personas.composer.presentMode")}
            </button>
          </div>
          <AdminButton variant="secondary" size="sm" onClick={onDuplicate}>
            {t("common.duplicate")}
          </AdminButton>
          <AdminButton variant="secondary" size="sm" onClick={onOpenVariants}>
            {t("personas.composer.variantsButton")}
          </AdminButton>
          <PersonaLibrarySaveAction
            personaId={personaId}
            origin={personaOrigin}
            onSaved={onLibraryOriginChange}
            onToast={onToast}
          />
          <AdminButton
            variant="primary"
            size="sm"
            disabled={saving || deleting}
            onClick={() => {
              onSave()
              setSaved(true)
              window.setTimeout(() => setSaved(false), 2600)
            }}
          >
            {t("personas.composer.savePersona")}
          </AdminButton>
          {onDelete &&
            (confirmDelete ? (
              <>
                <AdminButton
                  variant="secondary"
                  size="sm"
                  disabled={deleting}
                  onClick={() => setConfirmDelete(false)}
                >
                  {t("common.cancel")}
                </AdminButton>
                <AdminButton
                  variant="secondary"
                  size="sm"
                  disabled={deleting}
                  onClick={onDelete}
                >
                  {t("personas.composer.confirmDeleteButton")}
                </AdminButton>
              </>
            ) : (
              <AdminButton
                variant="secondary"
                size="sm"
                disabled={deleting}
                onClick={() => setConfirmDelete(true)}
              >
                {t("common.delete")}
              </AdminButton>
            ))}
          <Link to="/personas/new" className="no-underline">
            <AdminButton variant="secondary" size="sm">
              {t("personas.list.newPersona")}
            </AdminButton>
          </Link>
        </div>
      </div>
      {saved && (
        <div className="toast">
          <div className="ck">✓</div>{t("personas.composer.savedToast")}
        </div>
      )}

      <div className="work" style={{ display: mode === "work" ? "flex" : "none" }}>
        <div className="layers-col">
          <div className="layer-h">{t("personas.composer.layerDemography")}</div>
          <LayerTable
            fieldOptions={fieldOptions}
            t={t}
            onChange={upd}
            rows={[
              { k: "age", l: t("personas.fields.age"), v: persona.age, locked: !!locks.age },
              { k: "kön", l: t("personas.fields.gender"), v: persona.kön, locked: !!locks.kön },
              { k: "ort", l: t("personas.fields.district"), v: persona.ort, locked: !!locks.ort },
              { k: "yrke", l: t("personas.fields.occupation"), v: persona.yrke, locked: !!locks.yrke },
              {
                k: "utbildning",
                l: t("personas.fields.education"),
                v: persona.utbildning,
                locked: !!locks.utbildning,
              },
              {
                k: "livssituation",
                l: t("personas.fields.lifeSituation"),
                v: persona.livssituation,
                locked: !!locks.livssituation,
              },
            ]}
          />
          <div className="layer-h">{t("personas.composer.layerValues")}</div>
          <LayerTable
            fieldOptions={fieldOptions}
            t={t}
            onChange={upd}
            rows={[
              { k: "lutning", l: t("personas.fields.leaning"), v: persona.lutning, locked: !!locks.lutning },
              {
                k: "sakfragor",
                l: t("personas.fields.issues"),
                v: persona.sakfragor,
                locked: !!locks.sakfragor,
              },
              {
                k: "fortroende",
                l: t("personas.fields.trust"),
                v: persona.fortroende,
                locked: !!locks.fortroende,
              },
            ]}
          />
          <div className="layer-h">{t("personas.composer.layerVoice")}</div>
          <LayerTable
            fieldOptions={fieldOptions}
            t={t}
            onChange={upd}
            rows={[
              { k: "ton", l: t("personas.fields.tone"), v: persona.ton, locked: !!locks.ton },
              {
                k: "sprak",
                l: t("personas.fields.languagePattern"),
                v: persona.sprak,
                locked: !!locks.sprak,
              },
              {
                k: "medievanor",
                l: t("personas.fields.mediaHabits"),
                v: persona.medievanor,
                locked: !!locks.medievanor,
              },
            ]}
          />
          <div className="layer-h pol">{t("personas.composer.layerPolitics")}</div>
          <LayerTable
            pol
            fieldOptions={fieldOptions}
            t={t}
            onChange={upd}
            rows={[
              {
                k: "parti",
                l: t("personas.fields.partyPreference"),
                v: persona.parti,
                locked: !!locks.parti,
              },
              {
                k: "valdeltagande",
                l: t("personas.fields.turnout"),
                v: persona.valdeltagande,
                locked: !!locks.valdeltagande,
              },
            ]}
          />
          <div className="layer-h">{t("personas.composer.layerEverydayDetail")}</div>
          <div className="anekdot-layer">
            <PersonaAnekdotEditor
              value={persona.anekdot ?? "—"}
              className="cell-input"
              onChange={(v) => upd("anekdot", v)}
            />
            <p className="anekdot-hint">{t("personas.composer.anecdoteHint")}</p>
          </div>
        </div>
        <div className="chat-col">
          <div className="chat-top">
            <div className="ic-switch">
              <button
                type="button"
                className={icMode === "character" ? "on" : ""}
                onClick={() => setIcMode("character")}
              >
                {t("personas.composer.inCharacter")}
              </button>
              <button
                type="button"
                className={icMode === "interview" ? "on" : ""}
                onClick={() => setIcMode("interview")}
              >
                {t("personas.composer.interviewTab")}
              </button>
            </div>
            <AdminButton
              variant="secondary"
              size="sm"
              disabled={!personaId || chatBusy || messages.length === 0}
              onClick={() => setConfirmClearInterview(true)}
            >
              {clearChatLabel}
            </AdminButton>
            <AdminButton
              variant="secondary"
              size="sm"
              disabled={!personaId || chatBusy || messages.length === 0}
              onClick={() => void regenerate()}
            >
              ↻ {t("personas.composer.regenerateAnswer")}
            </AdminButton>
          </div>
          <MessengerChat
            messages={messages}
            optimisticUser={optimisticUser}
            typing={chatTyping}
            streamText={streamText}
            draft={draft}
            onDraftChange={setDraft}
            onSend={() => sendMessage(draft)}
            busy={chatBusy}
            ready={chatReady}
            disabled={!personaId}
            suggestions={suggestions}
            onSuggestion={sendMessage}
            placeholder={
              personaId
                ? t("personas.composer.messagePlaceholder")
                : t("personas.composer.savePersonaFirst")
            }
            empty={
              <div className="bub them">
                {!personaId
                  ? t("personas.composer.saveToInterviewChat")
                  : t("personas.composer.askToStart")}
              </div>
            }
            renderActions={
              personaId
                ? (m) => (
                    <ChatMessageActions
                      message={m}
                      busy={chatBusy}
                      onDelete={setConfirmDeleteMessageId}
                      onResend={(messageId) => void resendMessage(messageId)}
                    />
                  )
                : undefined
            }
          />
        </div>
      </div>

      <div className={"present" + (mode === "present" ? " show" : "")}>
        <div className="p-portrait-col">
          <div
            className="flex h-[260px] w-full items-center justify-center rounded bg-db-ink-100 text-sm text-[color:var(--text-muted)]"
          >
            {t("personas.profile.portraitOf", { name: persona.name })}
          </div>
          <h1 className="p-name" style={{ fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
            {persona.name}
          </h1>
          <div className="p-tag">
            {t("personas.profile.tagLine", {
              age: persona.age,
              occupation: persona.yrke,
              district: persona.ort,
              party: persona.parti,
            })}
          </div>
          <div className="p-sec">
            <div className="p-num">I.</div>
            <div className="p-lbl">{t("personas.profile.sectionDemography")}</div>
            <p>
              {t("personas.profile.demographyParagraph", {
                name: persona.name,
                district: persona.ort,
                lifeSituation: persona.livssituation,
                occupation: persona.yrke,
                education: persona.utbildning,
              })}
            </p>
          </div>
          <div className="p-sec">
            <div className="p-num">II.</div>
            <div className="p-lbl">{t("personas.profile.sectionValues")}</div>
            <p>
              {t("personas.profile.valuesParagraph", {
                leaning: persona.lutning,
                issues: persona.sakfragor,
                trust: persona.fortroende,
              })}
            </p>
          </div>
          <div className="p-sec">
            <div className="p-num">III.</div>
            <div className="p-lbl">{t("personas.profile.sectionVoice")}</div>
            <p>
              {t("personas.profile.voiceParagraph", {
                tone: persona.ton,
                language: persona.sprak,
                media: persona.medievanor,
              })}
            </p>
          </div>
          <div className="p-sec pol">
            <div className="p-num">IV.</div>
            <div className="p-lbl">{t("personas.profile.sectionPolitics")}</div>
            <p>
              {t("personas.profile.politicsParagraph", {
                party: persona.parti,
                turnout: persona.valdeltagande,
              })}
            </p>
          </div>
          <PersonaAnekdotPresentation profile={persona} />
        </div>
        <div className="p-interview">
          <div
            className="p-interview-head"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <h3 style={{ fontStyle: "italic", fontSize: 22, margin: 0 }}>
              {t("personas.composer.interviewTab")}
            </h3>
            {personaId && messages.length > 0 ? (
              <AdminButton
                variant="secondary"
                size="sm"
                disabled={chatBusy}
                onClick={() => setConfirmClearInterview(true)}
              >
                {clearChatLabel}
              </AdminButton>
            ) : null}
          </div>
          <MessengerChat
            messages={messages}
            optimisticUser={optimisticUser}
            typing={chatTyping}
            streamText={streamText}
            draft={draft}
            onDraftChange={setDraft}
            onSend={() => sendMessage(draft)}
            busy={chatBusy}
            ready={chatReady}
            disabled={!personaId}
            suggestions={suggestions}
            onSuggestion={sendMessage}
            placeholder={t("personas.composer.askPersonaPlaceholder", {
              name: persona.name,
            })}
            empty={
              <div className="bub them">
                {!personaId
                  ? t("personas.composer.saveToInterviewPresent")
                  : t("personas.composer.noInterviewYet")}
              </div>
            }
            renderActions={
              personaId
                ? (m) => (
                    <ChatMessageActions
                      message={m}
                      busy={chatBusy}
                      onDelete={setConfirmDeleteMessageId}
                      onResend={(messageId) => void resendMessage(messageId)}
                    />
                  )
                : undefined
            }
          />
        </div>
      </div>
    </div>

      <ConfirmModal
        open={confirmClearInterview}
        titleId="clear-interview-confirm-title"
        title={clearConfirmTitle}
        description={clearConfirmDescription}
        onClose={() => {
          if (!chatBusy) setConfirmClearInterview(false)
        }}
      >
        <div className="space-y-4">
          <p className="text-sm text-foreground">
            {messages.length === 1
              ? t("personas.composer.clearCountOne", {
                  mode: t(
                    icMode === "interview"
                      ? "personas.composer.modeInterview"
                      : "personas.composer.modeChat",
                  ),
                  name: persona.name,
                })
              : t("personas.composer.clearCountOther", {
                  count: messages.length,
                  mode: t(
                    icMode === "interview"
                      ? "personas.composer.modeInterview"
                      : "personas.composer.modeChat",
                  ),
                  name: persona.name,
                })}
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
              disabled={chatBusy}
              onClick={() => setConfirmClearInterview(false)}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/20 disabled:opacity-50"
              disabled={chatBusy}
              onClick={() => void confirmClearInterviewAction()}
            >
              {chatBusy ? t("personas.composer.clearing") : clearChatLabel}
            </button>
          </div>
        </div>
      </ConfirmModal>

      <ConfirmModal
        open={confirmDeleteMessageId != null}
        titleId="delete-message-confirm-title"
        title={t("personas.composer.deleteMessageConfirmTitle")}
        description={t("personas.composer.deleteMessageConfirmDesc")}
        onClose={() => {
          if (!chatBusy) setConfirmDeleteMessageId(null)
        }}
      >
        {messagePendingDelete ? (
          <div className="space-y-4">
            <p className="text-sm text-foreground line-clamp-4">
              {messagePendingDelete.role === "assistant" ? (
                <>
                  <span className="font-medium">{persona.name}:</span>{" "}
                  {messagePendingDelete.content}
                </>
              ) : (
                <>
                  <span className="font-medium">{t("personas.composer.youLabel")}:</span>{" "}
                  <span className="italic">{messagePendingDelete.content}</span>
                </>
              )}
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                disabled={chatBusy}
                onClick={() => setConfirmDeleteMessageId(null)}
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/20 disabled:opacity-50"
                disabled={chatBusy}
                onClick={() => void confirmDeleteMessageAction()}
              >
                {chatBusy ? t("personas.composer.deletingMessage") : t("personas.composer.deleteMessage")}
              </button>
            </div>
          </div>
        ) : null}
      </ConfirmModal>
    </>
  )
}

export function PersonaComposerPage() {
  const { t } = useLocale()
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const startCreating = params.get("new") === "1" || id === "new"
  const existingId = !startCreating && id && id !== "new" ? id : null

  const [screen, setScreen] = useState<"create" | "edit" | "variants">(
    startCreating ? "create" : "edit",
  )
  const [createStep, setCreateStep] = useState<"choose" | "free" | "demografi" | "candidates">(
    "choose",
  )
  const [createOrigin, setCreateOrigin] = useState<PersonaOrigin>("manuell")
  const [candidates, setCandidates] = useState<EditablePersona[]>([])
  const [toast, setToast] = useState("")
  const [persona, setPersona] = useState<EditablePersona | null>(
    startCreating ? null : blankEditablePersona(),
  )
  const [personaId, setPersonaId] = useState<string | null>(existingId)
  const [loading, setLoading] = useState(!!existingId)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [freeText, setFreeText] = useState(
    "45-årig undersköterska, S-sympatisör men trött på partiet, sarkastisk",
  )
  const [demo, setDemo] = useState({
    age: "42",
    kön: "Kvinna",
    ort: "Distrikt A",
    yrke: "Handläggare",
    utbildning: "Högskola",
    livssituation: "Sambo, barn",
  })
  const [generating, setGenerating] = useState(false)
  const [fieldOptions, setFieldOptions] = useState<Record<string, string[]>>({})

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(""), 2400)
  }

  useEffect(() => {
    let cancelled = false
    listCatalog()
      .then((lists) => {
        if (!cancelled) setFieldOptions(catalogToFieldOptions(lists))
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          showToast(
            err instanceof ApiError ? err.message : t("personas.composer.fetchOptionsError"),
          )
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function runCandidateGenerate(
    mode: "beskrivning" | "demografi",
    count = 3,
  ) {
    setGenerating(true)
    try {
      const result = await generatePersonas({
        mode,
        freeText: mode === "beskrivning" ? freeText : "",
        demografi: mode === "demografi" ? demo : undefined,
        count,
      })
      setCandidates(
        result.candidates.map((c) => ({
          ...blankEditablePersona(),
          ...c,
          key: Math.random(),
        })),
      )
      setCreateStep("candidates")
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("personas.composer.generateError"))
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    if (!existingId) return
    let cancelled = false
    setLoading(true)
    getPersona(existingId)
      .then((detail) => {
        if (cancelled) return
        setPersona({ ...blankEditablePersona(), ...detail.profile })
        setPersonaId(detail.id)
        setCreateOrigin(detail.origin)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setToast(err instanceof ApiError ? err.message : t("personas.composer.fetchPersonaError"))
          window.setTimeout(() => setToast(""), 2400)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingId])

  function setPersonaState(updater: (p: EditablePersona) => EditablePersona) {
    setPersona((p) => (p ? updater(p) : p))
  }

  async function savePersona(target: EditablePersona, origin: PersonaOrigin) {
    setSaving(true)
    try {
      const body = editableToWrite(target, origin)
      if (personaId) {
        const saved = await updatePersona(personaId, body)
        setPersona({ ...blankEditablePersona(), ...saved.profile })
        setPersonaId(saved.id)
      } else {
        const saved = await createPersona(body)
        setPersona({ ...blankEditablePersona(), ...saved.profile })
        setPersonaId(saved.id)
        navigate(`/personas/${saved.id}`, { replace: true })
      }
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("common.saveError"))
      window.setTimeout(() => setToast(""), 2400)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <AdminShell>
        <div className="shell">
          <div className="mainarea">
            <div className="no-match">{t("personas.composer.loadingPersona")}</div>
          </div>
        </div>
      </AdminShell>
    )
  }

  return (
    <AdminShell>
      <div className="shell">
        <div className="mainarea">
          {screen === "create" && createStep === "choose" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                {t("personas.composer.createTitle")}
              </h1>
              <p style={{ color: "var(--text-muted)", marginTop: 8, maxWidth: 600 }}>
                {t("personas.composer.createIntro")}
              </p>
              <div className="entry-grid">
                {(
                  [
                    ["blank", t("personas.composer.blankTitle"), t("personas.composer.blankDesc"), "manuell"],
                    ["free", t("personas.origin.fromDescription"), t("personas.composer.descriptionDesc"), "beskrivning"],
                    ["demografi", t("personas.origin.fromDemographics"), t("personas.composer.demographicsDesc"), "demografi"],
                  ] as const
                ).map(([kind, title, desc, origin]) => (
                  <div
                    key={kind}
                    className="entry-card"
                    onClick={() => {
                      setCreateOrigin(origin)
                      if (kind === "blank") {
                        setPersona(blankEditablePersona())
                        setScreen("edit")
                      } else setCreateStep(kind)
                    }}
                  >
                    <Card className="gap-0 py-5 ring-1 ring-border">
                      <CardContent className="px-5">
                        <h3 style={{ font: "var(--text-h3)", marginBottom: 8 }}>{title}</h3>
                        <p style={{ color: "var(--text-muted)", fontSize: 13.5 }}>{desc}</p>
                      </CardContent>
                    </Card>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 24 }}>
                <AdminButton variant="secondary" onClick={() => navigate("/personas")}>
                  {t("personas.composer.backToLibrary")}
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "create" && createStep === "free" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                {t("personas.composer.describeTitle")}
              </h1>
              <div className="field" style={{ marginTop: 20 }}>
                <label>{t("personas.composer.freeTextLabel")}</label>
                <textarea value={freeText} onChange={(e) => setFreeText(e.target.value)} />
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <AdminButton variant="secondary" onClick={() => setCreateStep("choose")}>
                  {t("common.back")}
                </AdminButton>
                <AdminButton
                  variant="primary"
                  disabled={generating}
                  onClick={() => void runCandidateGenerate("beskrivning")}
                >
                  {generating ? t("personas.composer.generating") : t("personas.composer.generateCandidates")}
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "create" && createStep === "demografi" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                {t("personas.composer.demographicFieldsTitle")}
              </h1>
              <div className="form-grid" style={{ marginTop: 20 }}>
                {(
                  [
                    ["age", t("personas.fields.age")],
                    ["kön", t("personas.fields.gender")],
                    ["ort", t("personas.fields.district")],
                    ["yrke", t("personas.fields.occupation")],
                    ["utbildning", t("personas.fields.education")],
                    ["livssituation", t("personas.fields.lifeSituation")],
                  ] as const
                ).map(([k, label]) => {
                  const opts = fieldOptions[k]
                  return (
                    <div
                      className="field"
                      key={k}
                      style={k === "livssituation" ? { gridColumn: "1 / -1" } : undefined}
                    >
                      <label>{label}</label>
                      {opts && opts.length > 0 ? (
                        <select
                          className="dsearch"
                          value={demo[k]}
                          onChange={(e) => setDemo({ ...demo, [k]: e.target.value })}
                        >
                          {!opts.includes(demo[k]) && (
                            <option value={demo[k]}>{demo[k] || "—"}</option>
                          )}
                          {opts.map((o) => (
                            <option key={o} value={o}>
                              {o}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={demo[k]}
                          onChange={(e) => setDemo({ ...demo, [k]: e.target.value })}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <AdminButton variant="secondary" onClick={() => setCreateStep("choose")}>
                  {t("common.back")}
                </AdminButton>
                <AdminButton
                  variant="primary"
                  disabled={generating}
                  onClick={() => void runCandidateGenerate("demografi")}
                >
                  {generating ? t("personas.composer.generating") : t("personas.composer.generateCandidates")}
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "create" && createStep === "candidates" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                {t("personas.composer.pickCandidateTitle")}
              </h1>
              <p style={{ color: "var(--text-muted)", marginTop: 8 }}>
                {t("personas.composer.pickCandidateIntro")}
              </p>
              <div className="cand-grid">
                {candidates.map((c) => (
                  <div
                    className="cand-card"
                    key={c.key}
                    onClick={() => {
                      setPersona({ ...blankEditablePersona(), ...c })
                      setScreen("edit")
                    }}
                  >
                    <Card className="gap-0 py-5 ring-1 ring-border">
                      <CardContent className="px-5">
                        <div className="avatar" style={{ marginBottom: 10 }}>
                          {c.initials}
                        </div>
                        <div style={{ fontWeight: 700, fontSize: 15 }}>{c.name}</div>
                        <div
                          style={{
                            font: "var(--text-body-sm)",
                            color: "var(--text-muted)",
                            marginBottom: 10,
                          }}
                        >
                          {c.age} · {c.yrke} · {c.ort}
                        </div>
                        <div style={{ fontSize: 12.5, fontStyle: "italic" }}>{c.ton}</div>
                        <div
                          style={{
                            fontSize: 11.5,
                            color: "var(--db-gold-700)",
                            marginTop: 8,
                            fontWeight: 700,
                          }}
                        >
                          {c.lutning} · {c.parti}
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 24 }}>
                <AdminButton variant="secondary" onClick={() => setCreateStep("choose")}>
                  {t("common.back")}
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "edit" && persona && (
            <Editor
              persona={persona}
              personaId={personaId}
              personaOrigin={createOrigin}
              onLibraryOriginChange={setCreateOrigin}
              t={t}
              setPersona={setPersonaState}
              onOpenVariants={() => setScreen("variants")}
              onSave={() => {
                if (persona) void savePersona(persona, createOrigin)
              }}
              fieldOptions={fieldOptions}
              saving={saving}
              deleting={deleting}
              onToast={showToast}
              onDelete={
                personaId
                  ? () => {
                      void (async () => {
                        setDeleting(true)
                        try {
                          await deletePersona(personaId)
                          navigate("/personas")
                        } catch (err) {
                          setToast(
                            err instanceof ApiError ? err.message : t("common.deleteError"),
                          )
                          window.setTimeout(() => setToast(""), 2400)
                        } finally {
                          setDeleting(false)
                        }
                      })()
                    }
                  : undefined
              }
              onDuplicate={() => {
                if (personaId) {
                  void duplicatePersona(personaId)
                    .then((copy) => {
                      setToast(t("personas.composer.duplicatedToast"))
                      window.setTimeout(() => setToast(""), 2400)
                      navigate(`/personas/${copy.id}`)
                    })
                    .catch((err: unknown) => {
                      setToast(err instanceof ApiError ? err.message : t("common.duplicateError"))
                      window.setTimeout(() => setToast(""), 2400)
                    })
                  return
                }
                setPersona((p) => (p ? { ...p, name: p.name + " (kopia)" } : p))
                setToast(t("personas.composer.duplicatedToast"))
                window.setTimeout(() => setToast(""), 2400)
              }}
            />
          )}

          {screen === "variants" && persona && (
            <VariantsView
              base={persona}
              origin={createOrigin}
              onDone={() => setScreen("edit")}
              onToast={showToast}
              onOpen={(c) => {
                setPersona(c)
                setPersonaId(null)
                setScreen("edit")
              }}
            />
          )}
        </div>
        {toast && (
          <div className="toast">
            <div className="ck">✓</div>
            {toast}
          </div>
        )}
      </div>
    </AdminShell>
  )
}

function VariantsView({
  base,
  origin,
  onDone,
  onOpen,
  onToast,
}: {
  base: EditablePersona
  origin: PersonaOrigin
  onDone: () => void
  onOpen: (c: EditablePersona) => void
  onToast: (message: string) => void
}) {
  const { t } = useLocale()
  const [variants, setVariants] = useState<EditablePersona[]>([])
  const [loading, setLoading] = useState(true)
  const [savedIdx, setSavedIdx] = useState<number[]>([])
  const [busyIdx, setBusyIdx] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    generatePersonas({
      mode: "demografi",
      demografi: {
        age: base.age,
        kön: base.kön,
        ort: base.ort,
        yrke: base.yrke,
        utbildning: base.utbildning,
        livssituation: base.livssituation,
      },
      freeText: `Varianter av ${base.name}, lutning ${base.lutning}, ton ${base.ton}`,
      count: 5,
    })
      .then((result) => {
        if (!cancelled) {
          setVariants(
            result.candidates.map((c) => ({
              ...blankEditablePersona(),
              ...c,
              key: Math.random(),
            })),
          )
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          onToast(err instanceof ApiError ? err.message : t("personas.composer.variantsGenerateError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base.name, base.age, base.kön, base.ort, base.yrke])

  async function saveVariant(i: number, c: EditablePersona) {
    setBusyIdx(i)
    try {
      await createPersona(editableToWrite(c, origin))
      setSavedIdx((s) => (s.includes(i) ? s : [...s, i]))
    } finally {
      setBusyIdx(null)
    }
  }

  return (
    <div className="create-wrap">
      <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
        {t("personas.composer.variantsTitle", { name: base.name })}
      </h1>
      <p style={{ color: "var(--text-muted)", marginTop: 8, maxWidth: 640 }}>
        {t("personas.composer.variantsIntro")}
      </p>
      {loading ? (
        <div className="no-match">{t("personas.composer.generatingVariants")}</div>
      ) : (
      <div className="cand-grid">
        {variants.map((c, i) => (
          <div className="cand-card is-variant" key={c.key ?? i}>
            <Card className="gap-0 py-5 ring-1 ring-border">
              <CardContent className="px-5">
                <div className="avatar" style={{ marginBottom: 10 }}>
                  {c.initials}
                </div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{c.name}</div>
                <div
                  style={{
                    font: "var(--text-body-sm)",
                    color: "var(--text-muted)",
                    marginBottom: 10,
                  }}
                >
                  {c.age} · {c.yrke} · {c.ort}
                </div>
                <div style={{ fontSize: 12.5, fontStyle: "italic" }}>{c.ton}</div>
                <div
                  style={{
                    fontSize: 11.5,
                    color: "var(--db-gold-700)",
                    marginTop: 8,
                    marginBottom: 14,
                    fontWeight: 700,
                  }}
                >
                  {c.lutning} · {c.parti}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <AdminButton
                    variant={savedIdx.includes(i) ? "secondary" : "primary"}
                    size="sm"
                    style={{ flex: 1 }}
                    disabled={savedIdx.includes(i) || busyIdx === i}
                    onClick={() => void saveVariant(i, c)}
                  >
                    {savedIdx.includes(i) ? t("personas.composer.variantSaved") : t("common.save")}
                  </AdminButton>
                  <AdminButton
                    variant="secondary"
                    size="sm"
                    style={{ flex: 1 }}
                    onClick={() => onOpen(c)}
                  >
                    {t("common.open")}
                  </AdminButton>
                </div>
              </CardContent>
            </Card>
          </div>
        ))}
      </div>
      )}
      <div style={{ marginTop: 24, display: "flex", gap: 10, alignItems: "center" }}>
        <AdminButton variant="primary" onClick={onDone}>
          {t("personas.composer.doneBackTo", { name: base.name })}
        </AdminButton>
        <span style={{ font: "var(--text-body-sm)", color: "var(--text-muted)" }}>
          {t("personas.composer.savedOfFive", { count: savedIdx.length })}
        </span>
      </div>
    </div>
  )
}
