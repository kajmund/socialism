import { describe, expect, it } from "vitest"

import { isUrgentBargeIn } from "./liveSpeechBarge"

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
