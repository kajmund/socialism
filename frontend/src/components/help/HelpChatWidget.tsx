import { useState } from "react"
import { createPortal } from "react-dom"
import { HelpChatPanel } from "@/components/help/HelpChatPanel"
import { useLocale } from "@/i18n"
import { getHelpSessionId } from "@/lib/helpSession"

function HelpIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 15.5a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5Zm1.25-4.75c0 .69-.56 1.25-1.25 1.25s-1.25-.56-1.25-1.25V9.5c0-.69.56-1.25 1.25-1.25s1.25.56 1.25 1.25v3.25Z"
      />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M18.3 5.71a1 1 0 0 0-1.41 0L12 10.59 7.11 5.7A1 1 0 0 0 5.7 7.11L10.59 12l-4.89 4.89a1 1 0 1 0 1.41 1.41L12 13.41l4.89 4.89a1 1 0 0 0 1.41-1.41L13.41 12l4.89-4.89a1 1 0 0 0 0-1.4Z"
      />
    </svg>
  )
}

export function HelpChatWidget() {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const sessionId = getHelpSessionId()

  return createPortal(
    <div className="help-chat-launcher">
      {open ? (
        <div id="help-chat-panel" className="help-chat-shell theme-admin" role="presentation">
          <HelpChatPanel sessionId={sessionId} onClose={() => setOpen(false)} />
        </div>
      ) : null}
      <button
        type="button"
        className="help-chat-fab"
        aria-expanded={open}
        aria-controls="help-chat-panel"
        aria-label={open ? t("help.closeFab") : t("help.openFab")}
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? <CloseIcon /> : <HelpIcon />}
      </button>
    </div>,
    document.body,
  )
}
