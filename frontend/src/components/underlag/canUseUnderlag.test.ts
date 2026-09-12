import { describe, expect, it } from "vitest"

import type { UnderlagFile } from "@/api/underlag"

import { canUseUnderlag } from "./canUseUnderlag"

function sampleFile(overrides: Partial<UnderlagFile> = {}): UnderlagFile {
  return {
    id: "obj-1",
    kind: "underlag",
    filename: "brief.pdf",
    content_type: "application/pdf",
    size_bytes: 100,
    module: "expertgranskning",
    owner_user_id: "user-1",
    folder_id: null,
    extraction_status: "pending",
    extracted_text: null,
    created_at: "2026-09-04T10:00:00Z",
    ...overrides,
  }
}

describe("canUseUnderlag", () => {
  it("rejects failed, empty, and unsupported", () => {
    expect(canUseUnderlag(sampleFile({ extraction_status: "failed" }))).toBe(false)
    expect(canUseUnderlag(sampleFile({ extraction_status: "empty" }))).toBe(false)
    expect(canUseUnderlag(sampleFile({ extraction_status: "unsupported" }))).toBe(false)
  })

  it("accepts pending and ok PDFs without extracted text", () => {
    expect(canUseUnderlag(sampleFile({ extraction_status: "pending" }))).toBe(true)
    expect(
      canUseUnderlag(sampleFile({ extraction_status: "ok", extracted_text: null })),
    ).toBe(true)
  })

  it("accepts plain text and markdown", () => {
    expect(
      canUseUnderlag(
        sampleFile({
          content_type: "text/plain",
          filename: "a.txt",
          extraction_status: "pending",
        }),
      ),
    ).toBe(true)
    expect(
      canUseUnderlag(
        sampleFile({
          content_type: "text/markdown",
          filename: "a.md",
          extraction_status: "pending",
        }),
      ),
    ).toBe(true)
  })
})
