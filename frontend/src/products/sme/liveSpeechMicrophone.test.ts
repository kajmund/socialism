import { describe, expect, it } from "vitest"
import { liveSpeechMicrophone } from "./liveSpeechMicrophone"

describe("liveSpeechMicrophone", () => {
  it("keeps echo cancellation and leaves noise suppression to OpenAI", () => {
    expect(liveSpeechMicrophone.echoCancellation).toBe(true)
    expect(liveSpeechMicrophone.noiseSuppression).toBe(false)
  })
})
