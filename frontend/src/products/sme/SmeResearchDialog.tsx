import { useEffect, useRef, useState } from "react"
import { Microscope } from "lucide-react"
import { listWorkspaceFiles, type Workspace as ParentWorkspace, type WorkspaceFile } from "@/api/workspaces"
import { voiceWorkspaces, type Workspace } from "@/api/voiceWorkspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { WorkspaceResearchDialog } from "@/components/workspaces/WorkspaceResearchDialog"
import { workspaceFileState } from "@/components/workspaces/workspaceChatState"
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function SmeResearchDialog({ workspace, parent, onChanged }: { workspace: Workspace; parent: ParentWorkspace; onChanged: () => Promise<unknown> }) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  async function show() {
    setLoading(true); setError(null)
    try { const result = await listWorkspaceFiles(workspace.chat_id, workspace.customer_id); if (mounted.current) { setFiles(result); setOpen(true) } }
    catch (caught) { if (mounted.current) setError(workspaceErrorMessage(caught, t)) }
    finally { if (mounted.current) setLoading(false) }
  }
  const polling = files.some((file) => ["uploaded", "ingesting"].includes(workspaceFileState(file)))
  useEffect(() => {
    if (!open || !polling) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try { const result = await listWorkspaceFiles(workspace.chat_id, workspace.customer_id); if (!cancelled) setFiles(result) }
      catch (caught) { if (!cancelled) setError(workspaceErrorMessage(caught, t)) }
      if (!cancelled) timer = setTimeout(() => { void poll() }, 2500)
    }
    timer = setTimeout(() => { void poll() }, 2500)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [open, polling, workspace.chat_id, workspace.customer_id, t])

  async function start(objective: string, sourceObjectIds: string[]) {
    setBusy(true); setError(null)
    try {
      await voiceWorkspaces.tool(workspace.id, "start_research", { objective, confirmed: true, source_object_ids: sourceObjectIds })
      if (!mounted.current) return false
      await onChanged()
      return true
    } catch (caught) { if (mounted.current) setError(workspaceErrorMessage(caught, t)); return false }
    finally { if (mounted.current) setBusy(false) }
  }
  return <><AdminButton variant="secondary" size="sm" disabled={busy || loading} onClick={() => { void show() }}><Microscope size={16} aria-hidden="true" />{t("workspaceChat.startResearch")}</AdminButton>{error && !open ? <span role="alert" className="text-xs text-destructive">{error}</span> : null}<WorkspaceResearchDialog open={open} onOpenChange={setOpen} workspace={parent} files={files} busy={busy} error={error} onStart={start} /></>
}
