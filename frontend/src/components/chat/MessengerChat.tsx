import { useEffect, useRef, type ReactNode } from "react"
import { TypingIndicator } from "@/components/chat/TypingIndicator"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"

export type MessengerChatMessage = {
  id: number
  role: "user" | "assistant"
  content: string
}

type MessengerChatProps = {
  messages: MessengerChatMessage[]
  optimisticUser?: string | null
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
  /** Optional actions next to each bubble (delete/resend). */
  renderActions?: (message: MessengerChatMessage) => ReactNode
  className?: string
  messagesClassName?: string
}

/**
 * Shared Messenger-style thread + composer used by library chat and run interviews.
 */
export function MessengerChat({
  messages,
  optimisticUser = null,
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
  renderActions,
  className,
  messagesClassName,
}: MessengerChatProps) {
  const { t } = useLocale()
  const msgsRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const wasBusyRef = useRef(false)

  const showEmpty =
    messages.length === 0 && !optimisticUser && !typing && streamText == null

  useEffect(() => {
    const el = msgsRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, optimisticUser, typing, streamText])

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
        className={"chat-msgs" + (messagesClassName ? ` ${messagesClassName}` : "")}
      >
        {showEmpty ? empty : null}
        {messages.map((m) => (
          <div
            key={m.id}
            className={"chat-msg-row " + (m.role === "assistant" ? "them" : "me")}
          >
            <div className={"bub " + (m.role === "assistant" ? "them" : "me")}>
              {m.content}
            </div>
            {renderActions ? renderActions(m) : null}
          </div>
        ))}
        {optimisticUser ? (
          <div className="chat-msg-row me">
            <div className="bub me">{optimisticUser}</div>
          </div>
        ) : null}
        {typing ? <TypingIndicator /> : null}
        {streamText != null ? (
          <div className="chat-msg-row them">
            <div className="bub them chat-stream-cursor">{streamText}</div>
          </div>
        ) : null}
      </div>
      <div className="chat-input">
        <input
          ref={inputRef}
          placeholder={placeholder}
          value={draft}
          disabled={disabled}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              if (!busy && !disabled) onSend()
            }
          }}
        />
        <AdminButton
          variant="primary"
          size="sm"
          disabled={disabled || busy || !draft.trim() || !ready}
          onClick={() => onSend()}
        >
          {busy ? t("chat.sending") : t("chat.send")}
        </AdminButton>
      </div>
    </div>
  )
}
