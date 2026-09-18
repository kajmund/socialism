import { useAuth } from "@/auth/AuthProvider"
import { ProfileProposals } from "@/components/profiles/ProfileProposals"
import { ArrowLeft, UserRound, UsersRound } from "lucide-react"
import { useEffect, useState } from "react"
import { uploadMessageImageRaw } from "@/api/messages"
import type { SmeInboxItem, SmeMessage } from "@/api/sme"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { useLlmCapabilities } from "@/components/chat/useLlmCapabilities"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { SmeExpertMemoryButton } from "@/products/sme/SmeExpertMemoryButton"
import { SmeExpertToolsButton } from "@/products/sme/SmeExpertToolsButton"

type Props = {
  thread: SmeInboxItem | null
  messages: SmeMessage[]
  loading: boolean
  sending: boolean
  typing: boolean
  streamText: string | null
  error: string | null
  ready: boolean
  suggestions: string[]
  onSend: (message: string, imageSha256?: string | null) => boolean
  onBack: () => void
}

export function SmeChatPane({
  thread,
  messages,
  loading,
  sending,
  typing,
  streamText,
  error,
  ready,
  suggestions,
  onSend,
  onBack,
}: Props) {
  const { refreshProfile } = useAuth()
  const { t } = useLocale()
  const [draft, setDraft] = useState("")
  const [pendingImageSha, setPendingImageSha] = useState<string | null>(null)
  const [pendingImageUrl, setPendingImageUrl] = useState<string | null>(null)
  const [imageBusy, setImageBusy] = useState(false)
  const [imageError, setImageError] = useState<string | null>(null)
  const { allowImageAttach, imageAccept } = useLlmCapabilities()

  useEffect(() => {
    setDraft("")
    setPendingImageSha(null)
    setPendingImageUrl(null)
    setImageError(null)
  }, [thread?.thread_id, thread?.thread_type])

  useEffect(
    () => () => {
      if (pendingImageUrl) URL.revokeObjectURL(pendingImageUrl)
    },
    [pendingImageUrl],
  )

  function send() {
    if (!onSend(draft, pendingImageSha)) return
    setDraft("")
    setPendingImageSha(null)
    setPendingImageUrl(null)
    setImageError(null)
  }

  function clearPendingImage() {
    setPendingImageSha(null)
    setPendingImageUrl(null)
  }

  async function pickImage(file: File) {
    if (sending || imageBusy) return
    setImageBusy(true)
    setImageError(null)
    try {
      const { entry } = await uploadMessageImageRaw(file)
      setPendingImageSha(entry.sha256)
      setPendingImageUrl(URL.createObjectURL(file))
    } catch (err) {
      setImageError(
        err instanceof ApiError ? err.message : t("chat.imageUploadError"),
      )
    } finally {
      setImageBusy(false)
    }
  }

  if (!thread) {
    return (
      <section className="hidden min-w-0 flex-1 items-center justify-center bg-db-ink-50 text-center text-sm text-[color:var(--text-muted)] md:flex">
        <p className="max-w-sm font-[var(--font-body)]">
          {t("sme.selectConversation")}
        </p>
      </section>
    )
  }

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-db-ink-0">
      <header className="flex h-[72px] shrink-0 items-center gap-3 border-b border-[color:var(--border-hairline)] bg-db-ink-0 px-4">
        <button
          type="button"
          className="grid size-9 place-items-center rounded-[var(--radius-md)] text-[color:var(--text-body)] hover:bg-db-ink-100 md:hidden"
          aria-label={t("sme.back")}
          onClick={onBack}
        >
          <ArrowLeft size={21} />
        </button>
        <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-db-ink-950 text-db-gold-500">
          {thread.thread_type === "panel" ? (
            <UsersRound size={20} aria-hidden="true" />
          ) : (
            <UserRound size={20} aria-hidden="true" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <strong className="block truncate font-[var(--font-display)] text-base font-medium text-[color:var(--text-body)]">
            {thread.name}
          </strong>
          <span className="block truncate text-xs text-[color:var(--text-muted)]">
            {thread.thread_type === "panel"
              ? t("sme.groupMembers", { count: thread.member_names.length })
              : t("sme.activeNow")}
          </span>
        </span>
        {thread.thread_type === "expert" ? (
          <div className="flex items-center gap-2">
            <SmeExpertToolsButton
              key={`tools:${thread.thread_id}`}
              personaId={thread.thread_id}
            />
            <SmeExpertMemoryButton
              key={`memory:${thread.thread_id}`}
              personaId={thread.thread_id}
              name={thread.name}
            />
          </div>
        ) : null}
      </header>
      <MessengerChat
        className="sme-messenger-chat"
        messages={messages.map((message) => ({
          ...message,
          speakerName: message.persona_name,
        }))}
        typing={typing}
        streamText={streamText}
        draft={draft}
        onDraftChange={setDraft}
        onSend={send}
        busy={sending || imageBusy}
        ready={ready}
        placeholder={t("sme.messagePlaceholder")}
        suggestions={thread.thread_type === "expert" ? suggestions : []}
        onSuggestion={(question) => {
          if (onSend(question, null)) setDraft("")
        }}
        allowImageAttach={
          thread.thread_type === "expert" && allowImageAttach
        }
        imageAccept={imageAccept}
        pendingImageUrl={pendingImageUrl}
        onPickImage={(file) => void pickImage(file)}
        onClearImage={clearPendingImage}
        empty={
          <div className="bub them">
            {loading ? t("sme.loading") : t("personas.composer.askToStart")}
          </div>
        }
        notice={<>
          <div className="max-h-72 overflow-auto"><ProfileProposals conversation={thread.thread_type === "expert" ? `expert:${thread.thread_id}:interview` : `panel:${thread.thread_id}`} refreshKey={messages.length} onSaved={refreshProfile} /></div>
          {imageError || error ? (
            <span className="text-destructive" role="alert">
              {imageError || error}
            </span>
          ) : !ready && thread.thread_type === "expert" ? (
            t("sme.reconnecting")
          ) : null}
        </>}
      />
    </section>
  )
}
