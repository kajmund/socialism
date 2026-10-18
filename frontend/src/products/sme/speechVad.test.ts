import { describe, expect, it } from "vitest"
import { sileroThresholdsFromConfig } from "./speechVad"

describe("sileroThresholdsFromConfig", () => {
  it("defaults to the 0.5/0.35 band", () => {
    expect(sileroThresholdsFromConfig(undefined)).toEqual({
      threshold: 0.5,
      exitThreshold: 0.35,
    })
    expect(sileroThresholdsFromConfig({})).toEqual({
      threshold: 0.5,
      exitThreshold: 0.35,
    })
  })

  it("reads the server-sent Silero band", () => {
    expect(
      sileroThresholdsFromConfig({ silero_threshold: 0.6, silero_exit_threshold: 0.3 }),
    ).toEqual({ threshold: 0.6, exitThreshold: 0.3 })
  })

  it("ignores non-finite values", () => {
    expect(
      sileroThresholdsFromConfig({ silero_threshold: "high", silero_exit_threshold: null }),
    ).toEqual({ threshold: 0.5, exitThreshold: 0.35 })
  })
})
