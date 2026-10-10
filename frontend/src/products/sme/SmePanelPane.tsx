import { useEffect, useRef, useState } from "react"
import { Hand, Mic, MicOff, Phone, PhoneOff, UsersRound } from "lucide-react"
import { clearSmePanelMessages, listSmePanelMessages, markSmeThreadRead, sendSmePanelMessage, type SmeInboxItem, type SmeMessage } from "@/api/sme"
import { useAuth } from "@/auth/AuthProvider"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { ProfileProposals } from "@/components/profiles/ProfileProposals"
import { useLocale } from "@/i18n"
import { SmeClearChatButton } from "./SmeClearChatButton"
import { workspaceErrorMessage } from "./workspaceChatLogic"
import { useSmeGroupVoice } from "./useSmeGroupVoice"

export function SmePanelPane({ thread, onCleared }: { thread: SmeInboxItem; onCleared: () => void }) {
  const { t } = useLocale(); const { refreshProfile } = useAuth()
  const [messages, setMessages] = useState<SmeMessage[]>([]), [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [call, setCall] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const epoch = useRef(0)
  const localId = useRef(-1)

  function appendLocal(role: SmeMessage["role"], content: string, personaId: string | null, personaName: string | null) {
    const message: SmeMessage = {
      id: localId.current,
      role,
      content,
      created_at: new Date().toISOString(),
      persona_id: personaId,
      persona_name: personaName,
    }
    localId.current -= 1
    setMessages((rows) => [...rows, message])
  }

  const voice = useSmeGroupVoice({
    panelId: thread.thread_id,
    enabled: call,
    onUserPartial: setPreview,
    onUserTranscript: (text) => appendLocal("user", text, null, null),
    onExpertSpeech: (personaId, name, text) => appendLocal("assistant", text, personaId, name),
  })

  useEffect(() => { const token = ++epoch.current; let cancelled = false; setLoading(true); setMessages([]); setError(null); setCall(false); setPreview(null); void listSmePanelMessages(thread.thread_id).then((rows) => { if (!cancelled && epoch.current === token) setMessages(rows) }).catch((caught: unknown) => { if (!cancelled && epoch.current === token) setError(workspaceErrorMessage(caught, t, "sme.chatError")) }).finally(() => { if (!cancelled && epoch.current === token) setLoading(false) }); void markSmeThreadRead("panel", thread.thread_id).catch((caught: unknown) => { if (!cancelled && epoch.current === token) setError(workspaceErrorMessage(caught, t, "sme.chatError")) }); return () => { cancelled = true } }, [t, thread.thread_id])

  async function clearMessages() {
    const token = ++epoch.current
    await clearSmePanelMessages(thread.thread_id)
    if (epoch.current !== token) return
    setMessages([]); setDraft(""); setError(null); setPreview(null)
    onCleared()
  }

  async function send() {
    const text = draft.trim(); if (!text || busy) return
    setBusy(true); setError(null)
    try {
      const created = await sendSmePanelMessage(thread.thread_id, text)
      setMessages((rows) => [...new Map([...rows, ...created].map((message) => [message.id, message])).values()])
      setDraft("")
      await markSmeThreadRead("panel", thread.thread_id)
      if (call) voice.sendUtterance(text)
    }
    catch (caught) { setError(workspaceErrorMessage(caught, t, "sme.chatError")) }
    finally { setBusy(false) }
  }

  const hands = voice.snapshot?.hands ?? []
  const members = voice.snapshot?.members ?? []
  const handName = (id: string) => members.find((member) => member.id === id)?.name ?? id
  const callStatus = call ? t(`voiceWorkspaceChat.${voice.status}`) : null

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-white">
      <header className="flex h-[72px] shrink-0 items-center gap-3 border-b px-4">
        <span className="grid size-10 place-items-center rounded-xl bg-db-ink-950 text-db-gold-500">
          <UsersRound size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <strong className="block truncate text-sm">{thread.name}</strong>
          <span className="text-xs text-muted-foreground" role="status">
            {t("sme.groupMembers", { count: thread.member_names.length })}
            {callStatus ? ` · ${callStatus}` : ""}
            {voice.snapshot?.floor_name ? ` · ${voice.snapshot.floor_name}` : ""}
          </span>
        </div>
        <SmeClearChatButton name={thread.name} disabled={loading || busy || messages.length === 0} onClear={clearMessages} />
      </header>
      {hands.length > 0 && (
        <div className="flex shrink-0 flex-wrap gap-1 border-b px-4 py-2 text-xs">
          {hands.map((id) => (
            <button
              key={id}
              type="button"
              className="rounded-full border px-2 py-1 hover:bg-muted"
              onClick={() => voice.grantFloor(id)}
              title={t("sme.raisedHands")}
            >
              <Hand size={12} className="mr-1 inline" />
              {handName(id)}
            </button>
          ))}
        </div>
      )}
      <MessengerChat
        className="sme-messenger-chat"
        messages={messages.map((message) => ({ ...message, speakerName: message.persona_name }))}
        draft={draft}
        onDraftChange={setDraft}
        onSend={() => { void send() }}
        busy={busy}
        typing={busy}
        streamText={preview}
        placeholder={t("sme.messagePlaceholder")}
        empty={<div className="bub them">{loading ? t("sme.loading") : t("personas.composer.askToStart")}</div>}
        inputAction={
          <div className="flex items-center gap-1">
            {call ? (
              <button
                type="button"
                className="grid size-8 place-items-center rounded border"
                aria-label={t(voice.muted ? "voiceWorkspaceChat.unmute" : "voiceWorkspaceChat.mute")}
                onClick={voice.toggleMute}
              >
                {voice.muted ? <MicOff size={16} /> : <Mic size={16} />}
              </button>
            ) : null}
            <button
              type="button"
              disabled={voice.status === "connecting"}
              className={`grid size-8 place-items-center rounded border ${call ? "border-db-gold-500 bg-db-gold-100 text-db-gold-700" : ""}`}
              aria-label={t(call ? "voiceWorkspaceChat.voiceStop" : "voiceWorkspaceChat.voiceStart")}
              aria-pressed={call}
              onClick={() => { setPreview(null); if (!call) void voice.primeAudio(); setCall((value) => !value) }}
            >
              {call ? <PhoneOff size={16} /> : <Phone size={16} />}
            </button>
          </div>
        }
        notice={
          <>
            <div className="max-h-40 overflow-auto">
              <ProfileProposals conversation={`panel:${thread.thread_id}`} refreshKey={messages.length} onSaved={refreshProfile} />
            </div>
            {voice.error ? <span className="text-destructive" role="alert">{voice.error}</span> : null}
            {error ? <span className="text-destructive" role="alert">{error}</span> : null}
          </>
        }
      />
    </section>
  )
}
