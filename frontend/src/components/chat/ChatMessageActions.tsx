import type { MessengerChatMessage } from "@/components/chat/MessengerChat"
import { useLocale } from "@/i18n"

type ChatMessageActionsProps = {
  message: MessengerChatMessage
  busy: boolean
  onDelete: (messageId: number) => void
  onResend: (messageId: number) => void
}

export function ChatMessageActions({
  message,
  busy,
  onDelete,
  onResend,
}: ChatMessageActionsProps) {
  const { t } = useLocale()
  const resendLabel =
    message.role === "user"
      ? t("personas.composer.resendMessage")
      : t("personas.composer.regenerateAnswer")
  const deleteLabel = t("personas.composer.deleteMessage")

  return (
    <div className="chat-msg-actions">
      <button
        type="button"
        className="chat-msg-resend"
        title={resendLabel}
        disabled={busy}
        onClick={() => onResend(message.id)}
        aria-label={resendLabel}
      >
        ↻
      </button>
      <button
        type="button"
        className="chat-msg-delete"
        title={deleteLabel}
        disabled={busy}
        onClick={() => onDelete(message.id)}
        aria-label={deleteLabel}
      >
        ×
      </button>
    </div>
  )
}
