import { describe, expect, it } from "vitest"

import type { UnderlagFile } from "@/api/underlag"

function canUseUnderlag(file: UnderlagFile): boolean {
  return file.extraction_status === "ok" && Boolean(file.extracted_text?.trim())
}

function sampleFile(overrides: Partial<UnderlagFile> = {}): UnderlagFile {
  return {
    id: "obj-1",
    filename: "brief.pdf",
    module: "expertgranskning",
    content_type: "application/pdf",
    size_bytes: 100,
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
      canUseUnderlag(
        sampleFile({ extraction_status: "ok", extracted_text: "   \n" }),
      ),
    ).toBe(false)
  })

  it("accepts ok extraction with text", () => {
    expect(
      canUseUnderlag(
        sampleFile({ extraction_status: "ok", extracted_text: "Underlagstext" }),
      ),
    ).toBe(true)
  })
})
