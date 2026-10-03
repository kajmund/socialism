import { useCallback, useEffect, useRef, useState } from "react"
import { createWorkspaceChat, getWorkspaceChat, listWorkspaceChats, listWorkspaceFiles, listWorkspaceResearch, listWorkspaces, type Workspace, type WorkspaceChat, type WorkspaceFile, type WorkspaceResearchJob } from "@/api/workspaces"
import { ApiError } from "@/lib/api"
import { useLocale } from "@/i18n"
import { workspaceFileState } from "./workspaceChatState"

export function useWorkspaceChat(customerId: number | undefined, enabled: boolean, personaId?: string) {
  const { t } = useLocale()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  const [chats, setChats] = useState<WorkspaceChat[]>([])
  const [chat, setChat] = useState<WorkspaceChat | null>(null)
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [jobs, setJobs] = useState<WorkspaceResearchJob[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)
  const snapshotRequest = useRef(0)

  useEffect(() => {
    let cancelled = false
    generation.current += 1
    setWorkspaces([])
    setWorkspaceId(null)
    setChat(null)
    setChats([])
    setFiles([])
    setJobs([])
    setError(null)
    if (!enabled) return
    setLoading(true)
    void listWorkspaces(customerId)
      .then((rows) => {
        if (cancelled) return
        setWorkspaces(rows)
        setWorkspaceId(rows.find((row) => row.kind === "company")?.id ?? null)
      })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof ApiError ? err.message : t("workspaceChat.loadError")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [customerId, enabled, t])

  useEffect(() => {
    let cancelled = false
    generation.current += 1
    setChat(null)
    setChats([])
    setFiles([])
    setJobs([])
    setError(null)
    if (!workspaceId) return
    setLoading(true)
    void listWorkspaceChats(workspaceId, customerId)
      .then((rows) => {
        if (cancelled) return
        const matching = rows.filter((row) => row.persona_id === (personaId ?? null))
        setChats(matching)
        setChat(matching[0] ?? null)
      })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof ApiError ? err.message : t("workspaceChat.loadError")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [workspaceId, customerId, personaId, t])

  const refresh = useCallback(async (chatId: string) => {
    const currentGeneration = generation.current
    const request = ++snapshotRequest.current
    const [current, documents, research] = await Promise.all([
      getWorkspaceChat(chatId, customerId),
      listWorkspaceFiles(chatId, customerId),
      listWorkspaceResearch(chatId, customerId),
    ])
    if (generation.current !== currentGeneration || snapshotRequest.current !== request) return
    setChat((previous) => previous?.id === chatId ? current : previous)
    setFiles(documents)
    setJobs(research)
    setChats((rows) => rows.map((row) => row.id === chatId ? current : row))
  }, [customerId])

  useEffect(() => {
    if (!chat?.id) return
    let cancelled = false
    const currentId = chat.id
    const currentGeneration = generation.current
    const request = ++snapshotRequest.current
    void Promise.all([listWorkspaceFiles(currentId, customerId), listWorkspaceResearch(currentId, customerId)])
      .then(([documents, research]) => {
        if (cancelled || generation.current !== currentGeneration || snapshotRequest.current !== request) return
        setFiles(documents)
        setJobs(research)
      })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof ApiError ? err.message : t("workspaceChat.loadError")) })
    return () => { cancelled = true }
  }, [chat?.id, customerId, t])

  const polling = files.some((file) => ["uploaded", "ingesting"].includes(workspaceFileState(file))) || jobs.some((job) => job.status === "pending" || job.status === "running")
  useEffect(() => {
    if (!chat?.id || !polling) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const currentId = chat.id
    async function poll() {
      try {
        await refresh(currentId)
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("workspaceChat.loadError"))
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 2500)
    }
    timer = setTimeout(() => void poll(), 2500)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [chat?.id, polling, refresh, t])

  async function newChat(): Promise<WorkspaceChat> {
    const currentGeneration = generation.current
    const created = await createWorkspaceChat(workspaceId ?? undefined, personaId, customerId)
    if (generation.current === currentGeneration) {
      generation.current += 1
      setChats((rows) => [created, ...rows])
      setChat(created)
      setFiles([])
      setJobs([])
    }
    return created
  }

  function selectChat(chatId: string) {
    generation.current += 1
    setChat(chats.find((row) => row.id === chatId) ?? null)
    setFiles([])
    setJobs([])
    setError(null)
  }

  function replaceChat(updated: WorkspaceChat) {
    setChat((current) => current?.id === updated.id ? updated : current)
    setChats((rows) => rows.map((row) => row.id === updated.id ? updated : row))
  }

  function addFile(file: WorkspaceFile) {
    snapshotRequest.current += 1
    setFiles((rows) => [...rows.filter((row) => row.id !== file.id), file])
  }

  return { workspaces, setWorkspaces, workspaceId, setWorkspaceId, chats, chat, files, addFile, jobs, loading, error, setError, newChat, selectChat, replaceChat, refresh }
}
