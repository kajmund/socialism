import { useState } from "react"
import { HelpChatPanel } from "@/components/help/HelpChatPanel"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { getHelpSessionId } from "@/lib/helpSession"

export function HelpChatWidget() {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const sessionId = getHelpSessionId()

  return (
    <>
      <div className="help-chat-fab">
        <AdminButton
          variant="primary"
          size="sm"
          aria-expanded={open}
          aria-controls="help-chat-panel"
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? t("help.closeFab") : t("help.openFab")}
        </AdminButton>
      </div>
      {open ? (
        <div id="help-chat-panel" className="help-chat-shell">
          <HelpChatPanel sessionId={sessionId} onClose={() => setOpen(false)} />
        </div>
      ) : null}
    </>
  )
}
