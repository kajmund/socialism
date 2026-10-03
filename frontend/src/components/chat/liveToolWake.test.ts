import { describe, expect, it } from "vitest"

import {
  deferredToolResult,
  isVoiceToolWake,
  shouldDeferLiveTool,
  voiceToolWakeText,
} from "@/components/chat/liveToolWake"

describe("live tool wake", () => {
  it("marks a later result so it is not stored as the user speaking", () => {
    const text = voiceToolWakeText("Omsättningen är 12.")
    expect(isVoiceToolWake(text)).toBe(true)
    expect(isVoiceToolWake("Vad är omsättningen?")).toBe(false)
    expect(JSON.parse(deferredToolResult())).toMatchObject({ status: "deferred" })
  })

  it("keeps a tool in the same turn while that utterance is still arriving", () => {
    expect(shouldDeferLiveTool("Kolla Volvo", "Kolla Volvo", false)).toBe(false)
    expect(shouldDeferLiveTool("Kolla Volvo", "Kolla Volvo AB", false)).toBe(false)
    expect(shouldDeferLiveTool("Kolla Volvo", "", false)).toBe(false)
    expect(shouldDeferLiveTool("Kolla Volvo", "En annan fråga", false)).toBe(true)
    expect(shouldDeferLiveTool("Kolla Volvo", "Kolla Volvo", true)).toBe(true)
  })
})