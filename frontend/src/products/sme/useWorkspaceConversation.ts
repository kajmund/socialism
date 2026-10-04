import { useCallback, useEffect, useRef, useState } from "react"
import type { Conversation as ConversationInstance, Callbacks } from "@elevenlabs/client"
import { voiceWorkspaces, type ChatSession, type WorkspaceMessage, type ToolResult } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import type { WorkspaceTurnSnapshot } from "./workspaceTurnSnapshot"
import { clientArguments, isCurrentConversation, workspaceErrorMessage } from "./workspaceChatLogic"

export type VoiceState = "disconnected" | "connecting" | "listening" | "speaking" | "paused" | "error"
const clientNames = ["open_ingest_picker", "show_evidence", "show_document", "focus_anchor", "show_comparison", "show_relations", "show_knowledge", "show_artifact"]
const serverNames = ["get_workspace_context", "ingest_source", "get_job_status", "search_knowledge", "read_source", "start_research", "compare_sources", "get_relations", "render_chart", "create_document", "revise_document", "export_document", "expert_tool"]
type Active = { connection: ConversationInstance; session: ChatSession; workspaceId: string; mode: "voice" | "text"; send: (text: string) => Promise<void>; drain: () => Promise<void> }
export function useWorkspaceConversation(props: {
  workspaceId: string | null; expertId: string | null
  snapshot: () => Promise<WorkspaceTurnSnapshot | null>
  onMessage: (message: WorkspaceMessage) => void; onPreview: (text: string | null) => void
  onTool: (name: string, args: Record<string, unknown>, isCurrent: () => boolean) => Promise<unknown>; onServerResult?: (name: string, result: ToolResult) => void; onError: (message: string) => void
}) {
  const { workspaceId, expertId } = props
  const { locale, t } = useLocale()
  const [status, setStatus] = useState<VoiceState>("disconnected")
  const [voice, setVoice] = useState(false)
  const [muted, setMuted] = useState(false)
  const latest = useRef(props); latest.current = props
  const generation = useRef(0)
  const active = useRef<Active | null>(null)
  const starting = useRef<Promise<Active> | null>(null)
  const closing = useRef(Promise.resolve())
  const mutedRef = useRef(false)
  const stop = useCallback(async () => {
    const previous = active.current; const drained = previous?.drain()
    generation.current += 1; starting.current = null
     active.current = null
    setVoice(false); setMuted(false); mutedRef.current = false; setStatus("disconnected"); latest.current.onPreview(null)
    if (!previous) { await closing.current; return }
    if (previous.mode === "voice") { previous.connection.setVolume({ volume: 0 }); previous.connection.setMicMuted(true) }
    const teardown = (async () => {
      await drained
      const outcomes = await Promise.allSettled([previous.connection.endSession(), voiceWorkspaces.end(previous.workspaceId, previous.session.session_id)])
      for (const result of outcomes) if (result.status === "rejected") latest.current.onError(workspaceErrorMessage(result.reason, t, "voiceWorkspaceChat.sessionError"))
    })()
    closing.current = teardown
    await teardown
  }, [t])
  useEffect(() => { void stop(); return () => { void stop() } }, [workspaceId, expertId, stop])
  const start = useCallback(async (mode: "voice" | "text"): Promise<Active> => {
    if (!workspaceId || !expertId) throw new Error(t("voiceWorkspaceChat.noExperts"))
    if (active.current?.mode === mode && active.current.connection.isOpen()) return active.current
    if (starting.current) return starting.current
    await stop()
    if (starting.current) return starting.current
    const currentGeneration = generation.current
    setStatus("connecting")
    const task = (async () => {
      const session = await voiceWorkspaces.start(workspaceId, expertId, mode, locale)
      const isCurrent = () => isCurrentConversation(currentGeneration, generation.current, { workspaceId, expertId }, latest.current)
      if (!isCurrent()) { await voiceWorkspaces.end(workspaceId, session.session_id); throw new Error(t("voiceWorkspaceChat.sessionError")) }
      let resolveBound!: () => void
      const bound = new Promise<void>((resolve) => { resolveBound = resolve })
      let connection: ConversationInstance | null = null
      let persistence = Promise.resolve()
      let userPersistence = Promise.resolve()
      const seen = new Set<string>(), pendingText: string[] = []
      let lastUserKey: string | null = null
      let lastAgentKey: string | null = null, sequence = 0, partial = "", agentTurn = 0, localMessageSequence = 0
      let speaking = false, interrupted = false
      const persist = (eventKey: string, kind: "user" | "agent" | "correction" | "complete", text: string, originalEventKey?: string) => {
        if (!isCurrent() || seen.has(eventKey)) return Promise.resolve()
        const capturedSnapshot = kind === "user" ? latest.current.snapshot() : null
        seen.add(eventKey)
        if (kind !== "complete") latest.current.onMessage({ id: -(Date.now() * 1000 + ++localMessageSequence), role: kind === "user" ? "user" : "agent", content: text, created_at: new Date().toISOString(), event_key: originalEventKey ?? eventKey, session_id: session.session_id })
        const action = persistence.then(async () => {
          await bound
          const snapshot = await capturedSnapshot
          const result = await voiceWorkspaces.event(workspaceId, session.session_id, { event_key: eventKey, kind, text, original_event_key: originalEventKey, ...(kind === "user" && snapshot ? { workspace_revision: snapshot.revision, context_snapshot: structuredClone(snapshot.state) } : {}) })
          if (!isCurrent()) return
          if (kind !== "complete") latest.current.onMessage({ id: result.message_id, role: kind === "user" ? "user" : "agent", content: text, created_at: new Date().toISOString(), event_key: originalEventKey ?? eventKey, session_id: session.session_id })
          if (kind === "user" && result.context) connection?.sendContextualUpdate(result.context)
        })
        if (kind === "user") userPersistence = action
        persistence = action.catch((error: unknown) => { if (isCurrent()) latest.current.onError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError")) })
        return action
      }
      const complete = (key = lastAgentKey) => key ? persist(`complete:${key}`, "complete", "", key) : Promise.resolve()
      const callbacks: Partial<Callbacks> = {
        onMessage: ({ role, message, event_id }) => {
          if (!isCurrent()) return
          const key = `${role}:${event_id ?? ++sequence}`
          if (seen.has(key)) return
          if (role === "user" && pendingText[0] === message) { pendingText.shift(); seen.add(key); return }
          if (role === "user") { agentTurn += 1; lastUserKey = key }
          if (role === "agent") { lastAgentKey = key; interrupted = false; partial = ""; latest.current.onPreview(null) }
          void persist(key, role, message).then(() => { if (role === "agent" && mode === "text") return complete(key) }).catch(() => undefined)
        },
        onAgentResponseCorrection: (event) => { if (isCurrent() && lastAgentKey) { const original = event.event_id != null ? `agent:${event.event_id}` : lastAgentKey; void persist(`correction:${original}:${++sequence}`, "correction", event.corrected_agent_response, original).catch(() => undefined); latest.current.onPreview(null) } },
        onAgentChatResponsePart: (part) => { if (isCurrent()) { if (part.type === "start") partial = part.text; else if (part.type === "delta") partial += part.text; if (part.type !== "stop") latest.current.onPreview(partial) } },
        onInterruption: () => { if (isCurrent()) { interrupted = true; partial = ""; latest.current.onPreview(null) } },
        onIncomingEvent: (event: unknown) => { if (isCurrent() && event && typeof event === "object" && "type" in event && event.type === "agent_response_complete" && mode === "text") void complete().catch(() => undefined) },
        onModeChange: ({ mode: nextMode }) => { if (!isCurrent()) return; if (mode === "voice" && speaking && nextMode === "listening" && !interrupted) void complete().catch(() => undefined); speaking = nextMode === "speaking"; setStatus(mutedRef.current ? "paused" : nextMode) },
        onError: (message) => { if (isCurrent()) { setStatus("error"); latest.current.onError(workspaceErrorMessage(new Error(message), t, "voiceWorkspaceChat.sessionError")) } },
        onDisconnect: () => { if (isCurrent()) { generation.current += 1; setStatus("disconnected"); setVoice(false); active.current = null; latest.current.onPreview(null); closing.current = persistence.finally(() => voiceWorkspaces.end(workspaceId, session.session_id)).catch((error: unknown) => latest.current.onError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError"))) } },
      }
      const clientTools = Object.fromEntries([...clientNames, ...serverNames].map((name) => [name, async (raw: unknown) => {
        const turn = agentTurn, turnKey = lastUserKey, turnPersistence = userPersistence, transcriptPersistence = persistence
        await bound; await turnPersistence
        await transcriptPersistence
        if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.sessionError"))
        const args = clientArguments(raw)
        const result = serverNames.includes(name)
          ? await voiceWorkspaces.sessionTool(workspaceId, session.session_id, name, connection?.getId() ?? requiredCredential(), turn, turnKey, args)
          : await latest.current.onTool(name, args, isCurrent)
        if (serverNames.includes(name) && isCurrent()) latest.current.onServerResult?.(name, result as ToolResult)
        if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.sessionError"))
        return JSON.stringify(result)
      }]))
      try {
        const credentials = mode === "voice" ? { conversationToken: session.conversation_token ?? requiredCredential(), connectionType: "webrtc" as const, textOnly: false } : { signedUrl: session.signed_url ?? requiredCredential(), connectionType: "websocket" as const, textOnly: true }
        const { Conversation } = await import("@elevenlabs/client")
        connection = await Conversation.startSession({ ...credentials, ...callbacks, clientTools, userId: session.session_id, dynamicVariables: session.dynamic_variables })
        if (mode === "voice") connection.setVolume({ volume: 0 })
        if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.sessionError"))
        await voiceWorkspaces.bind(workspaceId, session.session_id, connection.getId())
        if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.sessionError"))
        connection.sendContextualUpdate(session.context); resolveBound()
        if (mode === "voice") connection.setVolume({ volume: 1 })
        const connected = connection
        const current: Active = { connection, session, workspaceId, mode, send: async (text) => {
          agentTurn += 1; lastUserKey = `text:${crypto.randomUUID()}`; await persist(lastUserKey, "user", text)
          if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.sessionError"))
          pendingText.push(text); connected.sendUserMessage(text)
        }, drain: () => persistence }
        active.current = current; setVoice(mode === "voice"); setStatus("listening")
        return current
      } catch (error) {
        resolveBound(); await Promise.allSettled([connection?.endSession(), voiceWorkspaces.end(workspaceId, session.session_id)])
        if (isCurrent()) setStatus("error")
        throw error
      }
    })()
    starting.current = task
    try { return await task } catch (error) { if (generation.current === currentGeneration) setStatus("error"); throw error } finally { if (generation.current === currentGeneration) starting.current = null }
  }, [expertId, locale, stop, t, workspaceId])
  const send = useCallback(async (text: string) => { const current = active.current ?? await start("text"); await current.send(text) }, [start])
  const contextualUpdate = useCallback((text: string) => { active.current?.connection.sendContextualUpdate(text) }, [])
  const userActivity = useCallback(() => { active.current?.connection.sendUserActivity() }, [])
  const toggleMute = useCallback(() => { if (active.current?.mode !== "voice") return; mutedRef.current = !mutedRef.current; active.current.connection.setMicMuted(mutedRef.current); setMuted(mutedRef.current); setStatus(mutedRef.current ? "paused" : "listening") }, [])
  return { status, voice, muted, start, stop, send, contextualUpdate, userActivity, toggleMute }
}
function requiredCredential(): never { throw new Error("Missing private conversation credentials") }
