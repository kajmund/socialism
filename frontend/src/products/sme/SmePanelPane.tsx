import { useEffect, useRef, useState } from "react"
import { Hand, Mic, MicOff, UsersRound } from "lucide-react"
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
  const epoch = useRef(0)

  const voice = useSmeGroupVoice({
    panelId: thread.thread_id,
    enabled: true,
  })

  useEffect(() => { const token = ++epoch.current; let cancelled = false; setLoading(true); setMessages([]); setError(null); void listSmePanelMessages(thread.thread_id).then((rows) => { if (!cancelled && epoch.current === token) setMessages(rows) }).catch((caught: unknown) => { if (!cancelled && epoch.current === token) setError(workspaceErrorMessage(caught, t, "sme.chatError")) }).finally(() => { if (!cancelled && epoch.current === token) setLoading(false) }); void markSmeThreadRead("panel", thread.thread_id).catch((caught: unknown) => { if (!cancelled && epoch.current === token) setError(workspaceErrorMessage(caught, t, "sme.chatError")) }); return () => { cancelled = true } }, [t, thread.thread_id])

  async function clearMessages() {
    const token = ++epoch.current
    await clearSmePanelMessages(thread.thread_id)
    if (epoch.current !== token) return
    setMessages([]); setDraft(""); setError(null)
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
      voice.sendUtterance(text)
    }
    catch (caught) { setError(workspaceErrorMessage(caught, t, "sme.chatError")) }
    finally { setBusy(false) }
  }

  const floorName = voice.snapshot?.floor_name ?? null

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-white">
      <header className="flex h-[72px] shrink-0 items-center gap-3 border-b px-4">
        <span className="grid size-10 place-items-center rounded-xl bg-db-ink-950 text-db-gold-500">
          <UsersRound size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <strong className="block truncate text-sm">{thread.name}</strong>
          <span className="text-xs text-muted-foreground">
            {t("sme.groupMembers", { count: thread.member_names.length })}
            {voice.connected ? " · voice" : ""}
            {floorName ? ` · ${floorName}` : ""}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {voice.connected && (
            <button
              type="button"
              className="grid size-8 place-items-center rounded-full border text-xs"
              onClick={() => (voice.listening ? voice.stopListening() : void voice.startListening())}
              title={voice.listening ? "Stop listening" : "Start listening"}
            >
              {voice.listening ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
          )}
          {voice.snapshot && voice.snapshot.hands.length > 0 && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground" title="Raised hands">
              <Hand size={14} />
              {voice.snapshot.hands.length}
            </span>
          )}
          {voice.snapshot && voice.snapshot.source_checked.length > 0 && (
            <span className="text-xs text-db-gold-700" title="Source checked">
              ✓ {voice.snapshot.source_checked.length}
            </span>
          )}
          <SmeClearChatButton name={thread.name} disabled={loading || busy || messages.length === 0} onClear={clearMessages} />
        </div>
      </header>
      <MessengerChat
        className="sme-messenger-chat"
        messages={messages.map((message) => ({ ...message, speakerName: message.persona_name }))}
        draft={draft}
        onDraftChange={setDraft}
        onSend={() => { void send() }}
        busy={busy}
        typing={busy}
        placeholder={t("sme.messagePlaceholder")}
        empty={<div className="bub them">{loading ? t("sme.loading") : t("personas.composer.askToStart")}</div>}
        notice={
          <>
            <div className="max-h-40 overflow-auto">
              <ProfileProposals conversation={`panel:${thread.thread_id}`} refreshKey={messages.length} onSaved={refreshProfile} />
            </div>
            {voice.error ? <span className="text-destructive" role="alert">{voice.error}</span> : null}
            {error ? <span className="text-destructive" role="alert">{error}</span> : null}
            {floorName ? <span className="text-xs text-muted-foreground">Floor: {floorName}</span> : null}
          </>
        }
      />
    </section>
  )
}
