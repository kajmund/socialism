import { useRef, useState, type ReactNode } from "react"
import { Mic, MicOff, Paperclip, Phone, PhoneOff } from "lucide-react"
import { useAuth } from "@/auth/AuthProvider"
import type { SmeInboxItem } from "@/api/sme"
import type { SourceReference, WorkspaceMessage } from "@/api/voiceWorkspaces"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { ChatMarkdown } from "@/components/chat/ChatMarkdown"
import { ExpertAvatar } from "@/components/experts/ExpertAvatar"
import { ProfileProposals } from "@/components/profiles/ProfileProposals"
import { useLocale } from "@/i18n"
import { SmeExpertMemoryButton } from "./SmeExpertMemoryButton"
import { SmeExpertToolsButton } from "./SmeExpertToolsButton"
import { workspaceThreadKey } from "./workspaceChatLogic"
import type { VoiceState } from "./useWorkspaceConversation"

export function SmeChatPane({ workspaceId, parentWorkspaceId, thread, messages, references, loading, sending, preview, error, status, voice, muted, notice, onSend, onVoice, onMute, onIngest, onOpen, onEdit, onActivity }: {
  workspaceId: string; parentWorkspaceId: string; thread: SmeInboxItem | null; messages: WorkspaceMessage[]; references: SourceReference[]
  loading: boolean; sending: boolean; preview: string | null; error: string | null; status: VoiceState; voice: boolean; muted: boolean; notice?: ReactNode
  onSend: (text: string) => Promise<void>; onVoice: () => void; onMute: () => void; onIngest: () => void; onOpen: (id: string) => void; onEdit: () => void; onActivity: () => void
}) {
  const { t } = useLocale(); const { refreshProfile } = useAuth()
  const drafts = useRef(new Map<string, string>())
  const [, render] = useState(0)
  const draftKey = workspaceThreadKey(workspaceId, thread?.thread_type ?? "expert", thread?.thread_id ?? "")
  const draft = drafts.current.get(draftKey) ?? ""
  function setDraft(text: string) { drafts.current.set(draftKey, text); render((value) => value + 1); onActivity() }
  async function send() { const text = draft.trim(); if (!text) return; await onSend(text); setDraft("") }
  if (!thread) return <section className="grid h-full min-w-0 flex-1 place-items-center p-5 text-sm text-muted-foreground">{t("sme.selectConversation")}</section>
  return <section className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-white">
    <header className="flex h-[72px] shrink-0 items-center gap-3 border-b border-[color:var(--border-hairline)] px-4"><button type="button" className="shrink-0" aria-label={t("sme.expertEditorAria", { name: thread.name })} onClick={onEdit}><ExpertAvatar avatarUrl={thread.avatar_url} name={thread.name} className="grid size-10 place-items-center overflow-hidden rounded-xl bg-db-ink-950 text-db-gold-500" iconSize={20} /></button><span className="min-w-0 flex-1"><strong className="block truncate text-sm font-semibold">{thread.name}</strong><span className="block text-xs text-muted-foreground" role="status">{t(`voiceWorkspaceChat.${status}`)}</span></span><SmeExpertToolsButton personaId={thread.thread_id} /><SmeExpertMemoryButton key={`${parentWorkspaceId}:${thread.thread_id}`} personaId={thread.thread_id} name={thread.name} parentWorkspaceId={parentWorkspaceId} /></header>
    <MessengerChat className="sme-messenger-chat" messages={messages.map((message) => ({ ...message, role: message.role === "agent" ? "assistant" as const : "user" as const }))} draft={draft} onDraftChange={setDraft} onSend={() => { void send().catch(() => undefined) }} busy={sending} placeholder={t("sme.messagePlaceholder")} streamText={preview} renderMessageContent={(message) => <ChatMarkdown text={message.content} renderReference={(number) => { const reference = references.find((row) => row.number === number); return reference ? <button type="button" className="mx-0.5 inline-grid min-w-5 place-items-center rounded bg-db-ink-950 px-1 text-xs font-bold text-db-gold-500" aria-label={t("voiceWorkspaceChat.source", { number })} onClick={() => onOpen(reference.reference_id)}>{number}</button> : <span className="text-destructive" title={t("voiceWorkspaceChat.referenceUnavailable")}>[{number}]</span> }} />} inputAction={<div className="flex items-center gap-1"><button type="button" className="grid size-8 place-items-center rounded border" aria-label={t("voiceWorkspaceChat.addSource")} onClick={onIngest}><Paperclip size={16} /></button>{voice ? <button type="button" className="grid size-8 place-items-center rounded border" aria-label={t(muted ? "voiceWorkspaceChat.unmute" : "voiceWorkspaceChat.mute")} onClick={onMute}>{muted ? <MicOff size={16} /> : <Mic size={16} />}</button> : null}<button type="button" disabled={status === "connecting"} className={`grid size-8 place-items-center rounded border ${voice ? "border-db-gold-500 bg-db-gold-100 text-db-gold-700" : ""}`} aria-label={t(voice ? "voiceWorkspaceChat.voiceStop" : "voiceWorkspaceChat.voiceStart")} aria-pressed={voice} onClick={onVoice}>{voice ? <PhoneOff size={16} /> : <Phone size={16} />}</button></div>} empty={<div className="bub them">{loading ? t("sme.loading") : t("personas.composer.askToStart")}</div>} notice={<><div className="max-h-40 overflow-auto"><ProfileProposals conversation={`expert:${thread.thread_id}:interview`} refreshKey={messages.length} onSaved={refreshProfile} /></div>{preview ? <span className="text-xs text-muted-foreground">{t("voiceWorkspaceChat.preliminary")}</span> : null}{notice}{error ? <span className="text-destructive" role="alert">{error}</span> : null}</>} />
  </section>
}
