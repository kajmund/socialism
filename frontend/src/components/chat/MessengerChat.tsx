import { useEffect, useRef, type ReactNode } from "react"
import { CachedAuthImage } from "@/components/chat/CachedAuthImage"
import { ChatMarkdown } from "@/components/chat/ChatMarkdown"
import { TypingIndicator } from "@/components/chat/TypingIndicator"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"

export type MessengerChatMessage = {
  id: number
  role: "user" | "assistant"
  content: string
  asked_by?: "doctor" | "human" | null
  image_sha256?: string | null
  speakerName?: string | null
}

type MessengerChatProps = {
  messages: MessengerChatMessage[]
  optimisticUser?: string | null
  optimisticImageUrl?: string | null
  typing?: boolean
  streamText?: string | null
  draft: string
  onDraftChange: (value: string) => void
  onSend: () => void
  busy?: boolean
  ready?: boolean
  disabled?: boolean
  placeholder: string
  empty?: ReactNode
  /** Optional muted line above the composer (e.g. memory save notice). */
  notice?: ReactNode
  /** Optional actions next to each bubble (delete/resend). */
  renderActions?: (message: MessengerChatMessage) => ReactNode
  suggestions?: string[]
  onSuggestion?: (question: string) => void
  className?: string
  messagesClassName?: string
  /** When false, hide the image attach control entirely. */
  allowImageAttach?: boolean
  imageAccept?: string
  pendingImageUrl?: string | null
  onPickImage?: (file: File) => void
  onClearImage?: () => void
}

/**
 * Shared Messenger-style thread + composer used by library chat and run interviews.
 */
export function MessengerChat({
  messages,
  optimisticUser = null,
  optimisticImageUrl = null,
  typing = false,
  streamText = null,
  draft,
  onDraftChange,
  onSend,
  busy = false,
  ready = true,
  disabled = false,
  placeholder,
  empty = null,
  notice = null,
  renderActions,
  suggestions = [],
  onSuggestion,
  className,
  messagesClassName,
  allowImageAttach = false,
  imageAccept = "image/jpeg,image/png,image/gif,image/webp",
  pendingImageUrl = null,
  onPickImage,
  onClearImage,
}: MessengerChatProps) {
  const { t } = useLocale()
  const msgsRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const wasBusyRef = useRef(false)

  const showEmpty =
    messages.length === 0 &&
    !optimisticUser &&
    !optimisticImageUrl &&
    !typing &&
    streamText == null

  const canSend =
    Boolean(draft.trim() || pendingImageUrl) && !busy && !disabled && ready

  useEffect(() => {
    const el = msgsRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, optimisticUser, optimisticImageUrl, typing, streamText, suggestions])

  useEffect(() => {
    if (wasBusyRef.current && !busy && !disabled) {
      inputRef.current?.focus()
    }
    wasBusyRef.current = busy
  }, [busy, disabled])

  return (
    <div className={"messenger-chat" + (className ? ` ${className}` : "")}>
      <div
        ref={msgsRef}
        className={
          "chat-msgs nowheel" + (messagesClassName ? ` ${messagesClassName}` : "")
        }
      >
        {showEmpty ? empty : null}
        {messages.map((m) => (
          <div
            key={m.id}
            className={"chat-msg-row " + (m.role === "assistant" ? "them" : "me")}
          >
            <div className="chat-msg-stack">
              {m.role === "assistant" && m.speakerName ? (
                <span className="chat-msg-asked-by">{m.speakerName}</span>
              ) : null}
              {m.role === "user" && m.asked_by ? (
                <span className="chat-msg-asked-by">
                  {m.asked_by === "doctor"
                    ? t("runs.interview.askedByDoctor")
                    : t("runs.interview.askedByHuman")}
                </span>
              ) : null}
              <div className={"bub " + (m.role === "assistant" ? "them" : "me")}>
                {m.image_sha256 ? (
                  <CachedAuthImage
                    className="chat-msg-image mb-2 max-h-48 rounded"
                    sha256={m.image_sha256}
                    alt={t("chat.imageAlt")}
                  />
                ) : null}
                {m.content ? <ChatMarkdown text={m.content} /> : null}
              </div>
            </div>
            {renderActions ? renderActions(m) : null}
          </div>
        ))}
        {optimisticUser || optimisticImageUrl ? (
          <div className="chat-msg-row me">
            <div className="chat-msg-stack">
              <span className="chat-msg-asked-by">{t("runs.interview.askedByHuman")}</span>
              <div className="bub me">
                {optimisticImageUrl ? (
                  <img
                    className="chat-msg-image mb-2 max-h-48 rounded"
                    src={optimisticImageUrl}
                    alt={t("chat.imageAlt")}
                  />
                ) : null}
                {optimisticUser ? <ChatMarkdown text={optimisticUser} /> : null}
              </div>
            </div>
          </div>
        ) : null}
        {typing ? <TypingIndicator /> : null}
        {streamText != null ? (
          <div className="chat-msg-row them">
            <div className="bub them chat-stream-cursor">
              <ChatMarkdown text={streamText} />
            </div>
          </div>
        ) : null}
        {suggestions.length > 0 && !busy ? (
          <div
            className="chat-suggestions"
            role="group"
            aria-label={t("chat.suggestionsAria")}
          >
            {suggestions.map((question) => (
              <button
                key={question}
                type="button"
                className="chat-suggestion"
                disabled={disabled || !ready}
                onClick={() => onSuggestion?.(question)}
              >
                {question}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {notice ? <div className="chat-memory-notice">{notice}</div> : null}
      {pendingImageUrl ? (
        <div className="chat-image-preview flex items-center gap-2 px-2 pb-1">
          <img
            src={pendingImageUrl}
            alt={t("chat.imagePreviewAlt")}
            className="max-h-16 rounded border border-[color:var(--border-hairline)]"
          />
          <AdminButton
            type="button"
            variant="secondary"
            size="sm"
            disabled={disabled || busy}
            onClick={() => onClearImage?.()}
          >
            {t("chat.removeImage")}
          </AdminButton>
        </div>
      ) : null}
      <div className="chat-input nodrag">
        {allowImageAttach ? (
          <>
            <input
              ref={fileRef}
              type="file"
              accept={imageAccept}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ""
                if (file) onPickImage?.(file)
              }}
            />
            <AdminButton
              type="button"
              variant="secondary"
              size="sm"
              disabled={disabled || busy}
              aria-label={t("chat.attachImageAria")}
              onClick={() => fileRef.current?.click()}
            >
              {t("chat.attachImage")}
            </AdminButton>
          </>
        ) : null}
        <input
          ref={inputRef}
          placeholder={placeholder}
          value={draft}
          disabled={disabled}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              if (canSend) onSend()
            }
          }}
        />
        <AdminButton
          variant="primary"
          size="sm"
          disabled={!canSend}
          onClick={() => onSend()}
        >
          {busy ? t("chat.sending") : t("chat.send")}
        </AdminButton>
      </div>
    </div>
  )
}
