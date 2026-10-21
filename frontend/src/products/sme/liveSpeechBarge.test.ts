import { describe, expect, it } from "vitest"

import { isListenerCue, isUrgentBargeIn } from "./liveSpeechBarge"

describe("isUrgentBargeIn", () => {
  it("recognizes urgent stop words", () => {
    expect(isUrgentBargeIn("Stopp!")).toBe(true)
    expect(isUrgentBargeIn("nej")).toBe(true)
    expect(isUrgentBargeIn("Vänta lite")).toBe(true)
    expect(isUrgentBargeIn("Nej tack")).toBe(true)
  })

  it("leaves listener cues alone", () => {
    expect(isUrgentBargeIn("mm")).toBe(false)
    expect(isUrgentBargeIn("ja, precis")).toBe(false)
    expect(isUrgentBargeIn("")).toBe(false)
  })
})

describe("isListenerCue", () => {
  it("keeps confirmation words from stopping playback", () => {
    expect(isListenerCue("precis")).toBe(true)
    expect(isListenerCue("just det")).toBe(true)
    expect(isListenerCue("jajust")).toBe(true)
    expect(isListenerCue("stopp")).toBe(false)
  })
})
