import { useState } from "react"
import type { Workspace, WorkspaceState } from "@/api/workspaces"
import { ResearchMonitorPanel } from "@/components/research/ResearchMonitorPanel"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"

export function WorkspaceResearch({ workspace, onState }: { workspace: Workspace; onState: (change: (state: WorkspaceState) => WorkspaceState) => void }) {
  const { t } = useLocale()
  const [attempt, setAttempt] = useState<string | null>(null)
  if (!workspace.research?.length) return null
  return <><div className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-white px-4 py-2 text-xs"><strong>{t("workspaceChat.research")}</strong>{workspace.research.map((row, i) => <span key={row.attempt_id} className="flex items-center gap-2"><label className="flex items-center gap-1"><input type="checkbox" checked={workspace.state.research_attempt_ids.includes(row.attempt_id)} onChange={(event) => { const checked = event.target.checked; onState((state) => ({ ...state, research_attempt_ids: checked ? [...state.research_attempt_ids, row.attempt_id] : state.research_attempt_ids.filter((id) => id !== row.attempt_id) })) }} />{i + 1}</label><button type="button" className="underline underline-offset-2" onClick={() => setAttempt(row.attempt_id)}>{row.status === "failed" ? t("workspaceChat.failed") : row.status === "succeeded" ? t("workspaceChat.completed") : t("workspaceChat.processing")}</button></span>)}</div><Dialog open={attempt !== null} onOpenChange={(open) => { if (!open) setAttempt(null) }}><DialogContent className="theme-admin max-h-[85dvh] overflow-auto sm:max-w-3xl"><DialogHeader><DialogTitle>{t("workspaceChat.research")}</DialogTitle></DialogHeader>{attempt ? <ResearchMonitorPanel attemptId={attempt} /> : null}</DialogContent></Dialog></>
}
