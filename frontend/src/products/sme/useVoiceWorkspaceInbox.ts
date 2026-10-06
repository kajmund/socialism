import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { SmeInboxItem } from "@/api/sme"
import { voiceWorkspaces, type VoiceWorkspaceInboxItem, type WorkspaceMessage } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function voiceInboxItems(metadata: SmeInboxItem[], summaries: VoiceWorkspaceInboxItem[]): SmeInboxItem[] {
  const native = new Map(summaries.map((row) => [row.expert_id, row]))
  return metadata.map((item) => {
    if (item.thread_type === "panel") return item
    const summary = native.get(item.thread_id)
    return { ...item, preview: summary?.preview ?? "", last_message_at: summary?.last_message_at ?? null, unread_count: summary?.unread_count ?? 0 }
  })
}

type Selection = { workspaceId: string; expertId: string }

export function createVoiceInboxReads(read: (workspaceId: string, expertId: string) => Promise<unknown>, refresh: (workspaceId: string) => Promise<void>) {
  let selected: Selection | null = null, viewed: Selection | null = null
  const select = (workspaceId: string | null, expertId: string | null) => {
    if (selected?.workspaceId === workspaceId && selected?.expertId === expertId) return
    selected = workspaceId && expertId ? { workspaceId, expertId } : null
    viewed = null
  }
  const acknowledge = async (scope: Selection | null) => {
    if (!scope || scope !== selected) return
    try { await read(scope.workspaceId, scope.expertId) } catch (error) { if (scope === selected) throw error; return }
    if (scope === selected) await refresh(scope.workspaceId)
  }
  return {
    select,
    selection: () => selected,
    historyLoaded: (scope: Selection | null) => {
      if (!scope || scope !== selected) return Promise.resolve()
      viewed = scope
      return acknowledge(scope)
    },
    persisted: (message: WorkspaceMessage) => message.id > 0 && viewed === selected ? acknowledge(viewed) : Promise.resolve(),
  }
}

export function useVoiceWorkspaceInbox(workspaceId: string | null, expertId: string | null, metadata: SmeInboxItem[]) {
  const { t } = useLocale()
  const [snapshot, setSnapshot] = useState<{ workspaceId: string; rows: VoiceWorkspaceInboxItem[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const currentWorkspace = useRef(workspaceId), currentExpert = useRef(expertId), request = useRef(0), mounted = useRef(false), labels = useRef(t), loaded = useRef<string | null>(null)
  currentWorkspace.current = workspaceId; currentExpert.current = expertId; labels.current = t
  const report = useCallback((caught: unknown) => { if (mounted.current) setError(workspaceErrorMessage(caught, labels.current, "sme.loadError")) }, [])
  const refresh = useCallback(async (id = currentWorkspace.current) => {
    if (!mounted.current || !id || id !== currentWorkspace.current) return
    const epoch = ++request.current
    if (!loaded.current?.startsWith(`${id}:`)) setLoading(true)
    try {
      const rows = await voiceWorkspaces.inbox(id)
      if (!mounted.current || id !== currentWorkspace.current || epoch !== request.current) return
      const fingerprint = `${id}:${JSON.stringify(rows)}`
      setError(null)
      if (loaded.current !== fingerprint) { loaded.current = fingerprint; setSnapshot({ workspaceId: id, rows }) }
    } catch (caught) {
      if (id === currentWorkspace.current && epoch === request.current) report(caught)
    } finally {
      if (mounted.current && id === currentWorkspace.current && epoch === request.current) setLoading(false)
    }
  }, [report])
  const reads = useRef<ReturnType<typeof createVoiceInboxReads> | null>(null)
  if (!reads.current) reads.current = createVoiceInboxReads(voiceWorkspaces.read, refresh)
  const tracker = reads.current
  tracker.select(workspaceId, expertId)
  useEffect(() => {
    mounted.current = true
    tracker.select(currentWorkspace.current, currentExpert.current)
    return () => { mounted.current = false; request.current += 1; tracker.select(null, null) }
  }, [tracker])
  useEffect(() => {
    loaded.current = null
    setSnapshot(null); setError(null); setLoading(false)
    void refresh()
    const focused = () => { void refresh() }
    window.addEventListener("focus", focused)
    return () => { request.current += 1; window.removeEventListener("focus", focused) }
  }, [workspaceId, refresh])
  const items = useMemo(() => voiceInboxItems(metadata, snapshot?.workspaceId === workspaceId ? snapshot.rows : []), [metadata, snapshot, workspaceId])
  return {
    items,
    loading, error, refresh, report,
    selection: tracker.selection,
    historyLoaded: tracker.historyLoaded,
    persisted: tracker.persisted,
  }
}
