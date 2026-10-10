import { useEffect, useRef, useState } from "react"
import { UsersRound } from "lucide-react"
import { clearSmePanelMessages, listSmePanelMessages, markSmeThreadRead, sendSmePanelMessage, type SmeInboxItem, type SmeMessage } from "@/api/sme"
import { useAuth } from "@/auth/AuthProvider"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { ProfileProposals } from "@/components/profiles/ProfileProposals"
import { useLocale } from "@/i18n"
import { SmeClearChatButton } from "./SmeClearChatButton"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function SmePanelPane({ thread, onCleared }: { thread: SmeInboxItem; onCleared: () => void }) {
  const { t } = useLocale(); const { refreshProfile } = useAuth()
  const [messages, setMessages] = useState<SmeMessage[]>([]), [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const epoch = useRef(0)
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
    try { const created = await sendSmePanelMessage(thread.thread_id, text); setMessages((rows) => [...new Map([...rows, ...created].map((message) => [message.id, message])).values()]); setDraft(""); await markSmeThreadRead("panel", thread.thread_id) }
    catch (caught) { setError(workspaceErrorMessage(caught, t, "sme.chatError")) }
    finally { setBusy(false) }
  }
  return <section className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-white"><header className="flex h-[72px] shrink-0 items-center gap-3 border-b px-4"><span className="grid size-10 place-items-center rounded-xl bg-db-ink-950 text-db-gold-500"><UsersRound size={20} /></span><div className="min-w-0 flex-1"><strong className="block truncate text-sm">{thread.name}</strong><span className="text-xs text-muted-foreground">{t("sme.groupMembers", { count: thread.member_names.length })}</span></div><div className="ml-auto"><SmeClearChatButton name={thread.name} disabled={loading || busy || messages.length === 0} onClear={clearMessages} /></div></header><MessengerChat className="sme-messenger-chat" messages={messages.map((message) => ({ ...message, speakerName: message.persona_name }))} draft={draft} onDraftChange={setDraft} onSend={() => { void send() }} busy={busy} typing={busy} placeholder={t("sme.messagePlaceholder")} empty={<div className="bub them">{loading ? t("sme.loading") : t("personas.composer.askToStart")}</div>} notice={<><div className="max-h-40 overflow-auto"><ProfileProposals conversation={`panel:${thread.thread_id}`} refreshKey={messages.length} onSaved={refreshProfile} /></div>{error ? <span className="text-destructive" role="alert">{error}</span> : null}</>} /></section>
}
