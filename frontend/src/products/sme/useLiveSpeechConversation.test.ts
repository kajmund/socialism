import { afterEach, describe, expect, it, vi } from "vitest"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("LiveSpeechClient lifecycle", () => {
  it("stops a microphone stream that resolves after cancellation", async () => {
    vi.stubGlobal("window", { location: { hash: "", search: "" } })
    const { LiveSpeechClient } = await import("./useLiveSpeechConversation")
    let resolveMicrophone!: (stream: MediaStream) => void
    const microphone = new Promise<MediaStream>((resolve) => {
      resolveMicrophone = resolve
    })
    const stopTrack = vi.fn()
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn(() => microphone) },
    })
    const client = new LiveSpeechClient("workspace", "expert", "sv", {
      state: vi.fn(),
      message: vi.fn(),
      preview: vi.fn(),
      tool: vi.fn(async () => undefined),
      error: vi.fn(),
      trace: vi.fn(),
    })

    const starting = client.start()
    await client.stop()
    resolveMicrophone({
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream)

    await expect(starting).rejects.toMatchObject({ name: "AbortError" })
    expect(stopTrack).toHaveBeenCalledOnce()
  })

  it("forwards a model trace from the live-speech socket", async () => {
    vi.stubGlobal("window", { location: { hash: "", search: "" } })
    const { LiveSpeechClient } = await import("./useLiveSpeechConversation")
    const trace = vi.fn()
    const client = new LiveSpeechClient("workspace", "expert", "sv", {
      state: vi.fn(),
      message: vi.fn(),
      preview: vi.fn(),
      tool: vi.fn(async () => undefined),
      error: vi.fn(),
      trace,
    })
    client["handleControl"](
      JSON.stringify({
        type: "model_trace",
        kind: "message",
        text: "Jag läser avtalet.",
        thread_id: "expert",
      }),
    )
    expect(trace).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "message", text: "Jag läser avtalet." }),
    )
  })

  it("shows waiting speech as preview and ignores backchannel history", async () => {
    vi.stubGlobal("window", { location: { hash: "", search: "" } })
    const { LiveSpeechClient } = await import("./useLiveSpeechConversation")
    const preview = vi.fn()
    const message = vi.fn()
    const client = new LiveSpeechClient("workspace", "expert", "sv", {
      state: vi.fn(),
      message,
      preview,
      tool: vi.fn(async () => undefined),
      error: vi.fn(),
      trace: vi.fn(),
    })
    client["handleControl"](JSON.stringify({
      type: "assistant.waiting",
      turn_id: "turn",
      phrase_id: "started",
      text: "Jag väntar in lite svar här.",
    }))
    client["handleControl"](JSON.stringify({
      type: "transcript.backchannel",
      turn_id: "turn",
      text: "mm",
      classification: "backchannel",
    }))
    expect(preview).toHaveBeenCalledWith("Jag väntar in lite svar här.")
    expect(message).not.toHaveBeenCalled()
  })

  it("shows the opening line as an assistant message", async () => {
    vi.stubGlobal("window", { location: { hash: "", search: "" } })
    const { LiveSpeechClient } = await import("./useLiveSpeechConversation")
    const preview = vi.fn()
    const message = vi.fn()
    const client = new LiveSpeechClient("workspace", "expert", "sv", {
      state: vi.fn(),
      message,
      preview,
      tool: vi.fn(async () => undefined),
      error: vi.fn(),
      trace: vi.fn(),
    })
    client["handleControl"](JSON.stringify({
      type: "assistant.opening",
      turn_id: "opening",
      text: "Vi var inne på avtalet.",
    }))
    expect(message).toHaveBeenCalledWith(
      expect.objectContaining({ role: "agent", content: "Vi var inne på avtalet." }),
    )
    expect(preview).toHaveBeenCalledWith(null)
  })

  it("cancels the spoken turn for typed text without closing the session", async () => {
    vi.stubGlobal("window", { location: { hash: "", search: "" } })
    const { LiveSpeechClient } = await import("./useLiveSpeechConversation")
    const state = vi.fn()
    const client = new LiveSpeechClient("workspace", "expert", "sv", {
      state,
      message: vi.fn(),
      preview: vi.fn(),
      tool: vi.fn(async () => undefined),
      error: vi.fn(),
      trace: vi.fn(),
    })
    const send = vi.fn()
    client["send"] = send
    client["handleControl"](JSON.stringify({
      type: "transcript.final",
      turn_id: "turn-1",
      item_id: "item",
      text: "Hej",
    }))
    client.cancel("text_message")
    expect(send).toHaveBeenCalledWith({
      type: "turn.cancel",
      turn_id: "turn-1",
      reason: "text_message",
    })
    expect(state).not.toHaveBeenCalledWith("disconnected")
  })
})
