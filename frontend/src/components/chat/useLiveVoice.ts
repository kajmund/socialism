import { useCallback, useEffect, useRef, useState } from "react"
import {
  createPersonaLiveToken,
  runPersonaLiveTool,
  savePersonaLiveMemory,
} from "@/api/personas"
import {
  createLiveVoiceSession,
  type LiveVoiceError,
  type LiveVoiceSession,
  type LiveVoiceState,
} from "@/components/chat/liveVoice"

type UseLiveVoiceOptions = {
  personaId: string | null
  onError: (error: LiveVoiceError) => void
  onMemoryError: () => void
  onToolError: (name: string) => void
}

export function useLiveVoice({
  personaId,
  onError,
  onMemoryError,
  onToolError,
}: UseLiveVoiceOptions): {
  state: LiveVoiceState
  toggle: () => void
  microphoneMuted: boolean
  speakerMuted: boolean
  toggleMicrophone: () => void
  toggleSpeaker: () => void
} {
  const [snapshot, setSnapshot] = useState<{
    personaId: string | null
    state: LiveVoiceState
  }>({ personaId: null, state: "idle" })
  const [microphoneMuted, setMicrophoneMuted] = useState(false)
  const [speakerMuted, setSpeakerMuted] = useState(false)
  const sessionRef = useRef<LiveVoiceSession | null>(null)
  const onErrorRef = useRef(onError)
  const onMemoryErrorRef = useRef(onMemoryError)
  const onToolErrorRef = useRef(onToolError)
  onErrorRef.current = onError
  onMemoryErrorRef.current = onMemoryError
  onToolErrorRef.current = onToolError
  const state =
    snapshot.personaId === personaId && personaId
      ? snapshot.state
      : "idle"

  useEffect(() => {
    if (!personaId) return
    let disposed = false
    const sessionId = crypto.randomUUID()
    const session = createLiveVoiceSession({
      getSession: () => createPersonaLiveToken(personaId),
      onStateChange: (nextState) => {
        if (!disposed) setSnapshot({ personaId, state: nextState })
      },
      onError: (error) => {
        if (!disposed) onErrorRef.current(error)
      },
      onTurnComplete: (userMessage, assistantMessage) => {
        void savePersonaLiveMemory(personaId, {
          session_id: sessionId,
          user_message: userMessage,
          assistant_message: assistantMessage,
        }).catch(() => {
          if (!disposed) onMemoryErrorRef.current()
        })
      },
      onToolCall: async (call, userMessage, history) => {
        const response = await runPersonaLiveTool(personaId, {
          session_id: sessionId,
          name: call.name,
          arguments: call.arguments,
          history,
          user_message: userMessage,
        })
        return response.result
      },
      onToolError: (name) => {
        if (!disposed) onToolErrorRef.current(name)
      },
    })
    sessionRef.current = session
    return () => {
      disposed = true
      sessionRef.current = null
      void session.stop()
    }
  }, [personaId])

  const toggle = useCallback(() => {
    const session = sessionRef.current
    if (!session) return
    if (state === "active" || state === "connecting" || state === "ringing") {
      void session.stop()
    } else {
      setMicrophoneMuted(false)
      setSpeakerMuted(false)
      void session.start()
    }
  }, [state])

  const toggleMicrophone = useCallback(() => {
    const next = !microphoneMuted
    setMicrophoneMuted(next)
    sessionRef.current?.setMicrophoneMuted(next)
  }, [microphoneMuted])

  const toggleSpeaker = useCallback(() => {
    const next = !speakerMuted
    setSpeakerMuted(next)
    sessionRef.current?.setSpeakerMuted(next)
  }, [speakerMuted])

  return {
    state,
    toggle,
    microphoneMuted,
    speakerMuted,
    toggleMicrophone,
    toggleSpeaker,
  }
}
