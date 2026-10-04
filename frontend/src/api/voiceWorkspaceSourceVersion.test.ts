import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
vi.mock("@/lib/auth", () => ({ authAdapter: { getAccessToken: () => Promise.resolve("synthetic-token") } }))
vi.mock("@/lib/env", () => ({ env: { apiBaseUrl: "http://api.synthetic.invalid" } }))
import { api } from "@/lib/api"
import { requireSourceFileSha256, requireSourceVersion, voiceWorkspaces } from "./voiceWorkspaces"
const fetchMock = vi.fn()
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock) })
afterEach(() => { vi.unstubAllGlobals() })

describe("version-bound workspace original reads", () => {
  it("returns the original blob and its server version through the authenticated API", async () => {
    fetchMock.mockResolvedValue(new Response("synthetic PDF", { headers: { "Content-Type": "application/pdf", "X-Workspace-Source-Version": "b".repeat(64), "X-Workspace-File-Sha256": "a".repeat(64) } }))
    const result = await voiceWorkspaces.sourceFileWithVersion("canvas", "source")
    expect(await result.blob.text()).toBe("synthetic PDF")
    expect(result.blob.type).toBe("application/pdf")
    expect(result.sourceVersion).toBe("b".repeat(64))
    expect(result.sourceFileSha256).toBe("a".repeat(64))
    expect(fetchMock).toHaveBeenCalledWith("http://api.synthetic.invalid/voice-workspaces/canvas/sources/source/file", { headers: { Accept: "*/*", Authorization: "Bearer synthetic-token" } })
  })
  it("rejects a missing source version without another request or inferred version", async () => {
    fetchMock.mockResolvedValue(new Response("synthetic PDF"))
    await expect(voiceWorkspaces.sourceFileWithVersion("canvas", "source")).rejects.toThrow("workspace_source_version_missing")
    expect(fetchMock).toHaveBeenCalledTimes(1)
    for (const invalid of [null, undefined, "", "  ", 1, "short", "g".repeat(64)]) expect(() => requireSourceVersion(invalid)).toThrow("workspace_source_version_missing")
  })
  it("rejects a missing or invalid file hash without deriving it from another response", async () => {
    fetchMock.mockResolvedValue(new Response("synthetic PDF", { headers: { "X-Workspace-Source-Version": "b".repeat(64) } }))
    await expect(voiceWorkspaces.sourceFileWithVersion("canvas", "source")).rejects.toThrow("workspace_source_file_hash_missing")
    expect(fetchMock).toHaveBeenCalledTimes(1)
    for (const invalid of [null, "", "a".repeat(63), "g".repeat(64), "a".repeat(65)]) expect(() => requireSourceFileSha256(invalid)).toThrow("workspace_source_file_hash_missing")
  })
  it("preserves an authorization error before parsing a source version", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "workspace_source_not_found" }), { status: 404 }))
    await expect(voiceWorkspaces.sourceFileWithVersion("canvas", "source")).rejects.toMatchObject({ status: 404, message: "workspace_source_not_found" })
  })
  it("preserves the existing blob-only contract for other callers", async () => {
    fetchMock.mockResolvedValue(new Response("synthetic export"))
    expect(await (await api.getBlob("/exports/synthetic")).text()).toBe("synthetic export")
  })
})
