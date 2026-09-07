import { describe, expect, it } from "vitest"

import type { UnderlagFile } from "@/api/underlag"

import { canUseUnderlag } from "./canUseUnderlag"

function sampleFile(overrides: Partial<UnderlagFile> = {}): UnderlagFile {
  return {
    id: "obj-1",
    kind: "file",
    filename: "brief.pdf",
    content_type: "application/pdf",
    size_bytes: 100,
    module: "expertgranskning",
    owner_user_id: "user-1",
    folder_id: null,
    extraction_status: "failed",
    extracted_text: null,
    created_at: "2026-09-04T10:00:00Z",
    ...overrides,
  }
}

describe("canUseUnderlag", () => {
  it("rejects failed, empty, and whitespace-only extractions", () => {
    expect(canUseUnderlag(sampleFile())).toBe(false)
    expect(canUseUnderlag(sampleFile({ extraction_status: "empty" }))).toBe(false)
    expect(
      canUseUnderlag(sampleFile({ extraction_status: "ok", extracted_text: "   \n" })),
    ).toBe(false)
  })

  it("accepts ok extraction with text", () => {
    expect(
      canUseUnderlag(sampleFile({ extraction_status: "ok", extracted_text: "Underlagstext" })),
    ).toBe(true)
  })
})
