import { describe, expect, it } from "vitest"
import type { ExpertMemory } from "@/api/expertMemory"
import { clipNoticeText, memoryNoticeText } from "@/components/experts/memoryNotice"

const t = (key: string, params?: Record<string, string | number>) => {
  if (key === "experts.memory.nothing") return "nothing"
  if (key === "experts.memory.saved") return `saved:${params?.text}`
  if (key === "experts.memory.updated") return `updated:${params?.text}`
  if (key === "experts.memory.savedMany") return `many:${params?.text}:+${params?.count}`
  return key
}

function hit(text: string, event = "ADD"): ExpertMemory {
  return {
    id: text,
    text,
    source: "persona_chat",
    expert_id: "legal",
    expert_name: "Juristen",
    persona_id: "exp_1_legal",
    customer_id: 1,
    created_at: "",
    updated_at: "",
    event,
    image_sha256: null,
  }
}

describe("memoryNoticeText", () => {
  it("reports when nothing was saved", () => {
    expect(memoryNoticeText([], t)).toBe("nothing")
  })

  it("reports a single add or update", () => {
    expect(memoryNoticeText([hit("Ansvar")], t)).toBe("saved:Ansvar")
    expect(memoryNoticeText([hit("Ansvar", "UPDATE")], t)).toBe("updated:Ansvar")
  })

  it("summarizes several saved memories", () => {
    expect(memoryNoticeText([hit("A"), hit("B")], t)).toBe("many:A:+1")
  })

  it("clips long memory text for the notice", () => {
    const long = "x".repeat(120)
    expect(clipNoticeText(long).endsWith("…")).toBe(true)
    expect(clipNoticeText(long).length).toBeLessThan(long.length)
    expect(memoryNoticeText([hit(long)], t)).toBe(`saved:${clipNoticeText(long)}`)
  })
})
