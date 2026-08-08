import { useLocale } from "@/i18n"

/** Messenger-style three bouncing dots in a “them” bubble. */
export function TypingIndicator() {
  const { t } = useLocale()
  return (
    <div
      className="chat-msg-row them"
      role="status"
      aria-label={t("chat.typingAria")}
    >
      <div className="bub them typing-bub">
        <span className="typing-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </div>
    </div>
  )
}
