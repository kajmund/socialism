import { useEffect, useId, useLayoutEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Menu } from "lucide-react"
import type { Workspace as ParentWorkspace } from "@/api/workspaces"
import type { KnowledgeResult, KnowledgeScope, Workspace } from "@/api/voiceWorkspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { EvidenceSearchButton } from "./EvidenceSearchButton"
import { SmeResearchDialog } from "./SmeResearchDialog"

const menuItem = "w-full justify-start"

export function SmeWorkspaceActionsMenu({
  workspace,
  parent,
  knowledge,
  scope,
  onAddSource,
  onRefresh,
  onSearch,
  onOpen,
  onLeaveEvidence,
  onScope,
}: {
  workspace: Workspace
  parent: ParentWorkspace
  knowledge: KnowledgeResult
  scope: KnowledgeScope
  onAddSource: () => void
  onRefresh: () => Promise<unknown>
  onSearch: (query: string) => void
  onOpen: (id: string) => void
  onLeaveEvidence: () => void
  onScope: (scope: KnowledgeScope) => void
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const panelId = useId()
  useLayoutEffect(() => {
    if (!open) return
    function place() {
      const rect = root.current?.getBoundingClientRect()
      if (!rect) return
      setPosition({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) })
    }
    place()
    window.addEventListener("resize", place)
    window.addEventListener("scroll", place, true)
    return () => {
      window.removeEventListener("resize", place)
      window.removeEventListener("scroll", place, true)
    }
  }, [open])
  useEffect(() => {
    if (!open) return
    function outside(event: MouseEvent) {
      const target = event.target
      if (!(target instanceof Node)) return
      if (root.current?.contains(target) || panel.current?.contains(target)) return
      setOpen(false)
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", outside)
    document.addEventListener("keydown", escape)
    return () => {
      document.removeEventListener("mousedown", outside)
      document.removeEventListener("keydown", escape)
    }
  }, [open])

  const menu = <div id={panelId} ref={panel} role="menu" className={open ? "fixed z-40 grid w-72 gap-2 rounded-lg border bg-white p-2 shadow-lg" : "hidden"} style={open && position ? { top: position.top, right: position.right } : undefined}>
    <AdminButton variant="secondary" size="sm" className={menuItem} onClick={() => { setOpen(false); onAddSource() }}>{t("voiceWorkspaceChat.addSource")}</AdminButton>
    <SmeResearchDialog workspace={workspace} parent={parent} onChanged={onRefresh} className={menuItem} />
    <EvidenceSearchButton workspace={workspace} knowledge={knowledge} openFromWorkspace={workspace.state.view === "evidence"} onSearch={onSearch} onOpen={onOpen} onLeaveEvidence={onLeaveEvidence} className="flex h-9 w-full items-center justify-start gap-1.5 rounded-lg border px-3 text-sm" />
    <div className="grid gap-1" role="group" aria-label={t("voiceWorkspaceChat.knowledge")}>
      {(["workspace", "general", "research"] as KnowledgeScope[]).map((item) => <button key={item} type="button" aria-pressed={scope === item} className={`rounded-md px-3 py-1.5 text-left text-xs ${scope === item ? "bg-db-ink-950 font-medium text-db-gold-500" : "hover:bg-db-ink-50"}`} onClick={() => onScope(item)}>{t(`voiceWorkspaceChat.${item}`)}</button>)}
    </div>
  </div>

  return <div className="relative shrink-0" ref={root}>
    <button type="button" className="grid size-9 place-items-center rounded-lg border" aria-label={t("voiceWorkspaceChat.workspaceMenu")} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((current) => !current)}>
      <Menu size={17} />
    </button>
    {typeof document === "undefined" ? menu : createPortal(menu, document.body)}
  </div>
}
