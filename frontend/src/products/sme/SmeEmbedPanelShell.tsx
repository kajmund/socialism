import type { ReactNode } from "react"

export function SmeEmbedPanelShell({ children }: { children: ReactNode }) {
  return (
    <div className="theme-admin flex min-h-0 flex-1 flex-col overflow-auto bg-db-ink-0">
      {children}
    </div>
  )
}
