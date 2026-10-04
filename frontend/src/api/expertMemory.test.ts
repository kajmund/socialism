import { beforeEach, describe, expect, it, vi } from "vitest"
import { clearPersonaMemories, deletePersonaMemory, listPersonaMemories, updatePersonaMemory } from "./expertMemory"

const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock("@/lib/api", () => ({ api }))

describe("persona memories workspace scope", () => {
  beforeEach(() => vi.clearAllMocks())

  it("keeps the selected parent on read, edit, deletion and clearing", async () => {
    const parent = "parent/workspace"
    await listPersonaMemories("expert", parent)
    await updatePersonaMemory("expert", "memory", "Updated", parent)
    await deletePersonaMemory("expert", "memory", parent)
    await clearPersonaMemories("expert", parent)

    const path = "/personas/expert/memories"
    const query = "?workspace_id=parent%2Fworkspace"
    expect(api.get).toHaveBeenCalledWith(`${path}${query}`)
    expect(api.patch).toHaveBeenCalledWith(`${path}/memory${query}`, { text: "Updated" })
    expect(api.delete.mock.calls).toEqual([[`${path}/memory${query}`], [`${path}${query}`]])
  })

  it("preserves callers without a selected workspace", async () => {
    await listPersonaMemories("expert")
    await updatePersonaMemory("expert", "memory", "Updated")
    await deletePersonaMemory("expert", "memory")
    await clearPersonaMemories("expert")

    expect(api.get).toHaveBeenCalledWith("/personas/expert/memories")
    expect(api.patch).toHaveBeenCalledWith("/personas/expert/memories/memory", { text: "Updated" })
    expect(api.delete.mock.calls).toEqual([["/personas/expert/memories/memory"], ["/personas/expert/memories"]])
  })
})
