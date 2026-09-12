import { describe, expect, it, vi } from "vitest"

import { buildSections } from "./sections"
import {
  NoWordParagraphsError,
  NoWordSectionsError,
  prepareWordReview,
  startNewWordReview,
  submitPreparedWordReview,
} from "./startReview"
import {
  EmptyWordSelectionError,
  UnresolvedWordSelectionError,
  type WordTaskSnapshot,
} from "./word/taskSnapshot"

function snapshot(
  overrides: Partial<WordTaskSnapshot> = {},
): WordTaskSnapshot {
  return {
    paragraphs: [
      {
        index: 0,
        text: "Ett stycke.",
        style: "Normal",
        list_string: "",
      },
    ],
    scope: { type: "document" },
    ...overrides,
  }
}

describe("startNewWordReview", () => {
  it("does not resolve previous comments when selection is empty", async () => {
    const createJob = vi.fn()
    const resolvePreviousComments = vi.fn()
    await expect(
      startNewWordReview({
        captureSnapshot: async () => {
          throw new EmptyWordSelectionError()
        },
        buildSections,
        createJob,
        resolvePreviousComments,
      }),
    ).rejects.toBeInstanceOf(EmptyWordSelectionError)
    expect(createJob).not.toHaveBeenCalled()
    expect(resolvePreviousComments).not.toHaveBeenCalled()
  })

  it("does not resolve previous comments when selection is unresolved", async () => {
    const createJob = vi.fn()
    const resolvePreviousComments = vi.fn()
    await expect(
      startNewWordReview({
        captureSnapshot: async () => {
          throw new UnresolvedWordSelectionError()
        },
        buildSections,
        createJob,
        resolvePreviousComments,
      }),
    ).rejects.toBeInstanceOf(UnresolvedWordSelectionError)
    expect(createJob).not.toHaveBeenCalled()
    expect(resolvePreviousComments).not.toHaveBeenCalled()
  })

  it("does not resolve previous comments when job creation fails", async () => {
    const resolvePreviousComments = vi.fn()
    await expect(
      startNewWordReview({
        captureSnapshot: async () => snapshot(),
        buildSections,
        createJob: async () => {
          throw new Error("create_failed")
        },
        resolvePreviousComments,
      }),
    ).rejects.toThrow("create_failed")
    expect(resolvePreviousComments).not.toHaveBeenCalled()
  })

  it("resolves previous comments only after a new job is created", async () => {
    const order: string[] = []
    const jobId = await startNewWordReview({
      captureSnapshot: async () => {
        order.push("capture")
        return snapshot()
      },
      buildSections: (paragraphs) => {
        order.push("sections")
        return buildSections(paragraphs)
      },
      createJob: async () => {
        order.push("create")
        return "job-1"
      },
      resolvePreviousComments: async () => {
        order.push("resolve")
      },
    })
    expect(jobId).toBe("job-1")
    expect(order).toEqual(["capture", "sections", "create", "resolve"])
  })

  it("fails closed on an empty document snapshot", async () => {
    const createJob = vi.fn()
    const resolvePreviousComments = vi.fn()
    await expect(
      startNewWordReview({
        captureSnapshot: async () => snapshot({ paragraphs: [] }),
        buildSections,
        createJob,
        resolvePreviousComments,
      }),
    ).rejects.toBeInstanceOf(NoWordParagraphsError)
    expect(createJob).not.toHaveBeenCalled()
    expect(resolvePreviousComments).not.toHaveBeenCalled()
  })

  it("prepares a snapshot without creating a job", async () => {
    const prepared = await prepareWordReview({
      captureSnapshot: async () => snapshot(),
      buildSections,
    })
    expect(prepared.sections.length).toBeGreaterThan(0)
    expect(prepared.snapshot.paragraphs).toHaveLength(1)
  })

  it("submits the prepared snapshot without recapturing", async () => {
    const order: string[] = []
    const frozen = snapshot()
    const sections = buildSections(frozen.paragraphs)
    const jobId = await submitPreparedWordReview({
      snapshot: frozen,
      sections,
      createJob: async ({ snapshot: submitted, sections: submittedSections }) => {
        order.push("create")
        expect(submitted).toBe(frozen)
        expect(submittedSections).toBe(sections)
        return "job-frozen"
      },
      resolvePreviousComments: async () => {
        order.push("resolve")
      },
    })
    expect(jobId).toBe("job-frozen")
    expect(order).toEqual(["create", "resolve"])
  })

  it("fails closed when sections cannot be built", async () => {
    const createJob = vi.fn()
    const resolvePreviousComments = vi.fn()
    await expect(
      startNewWordReview({
        captureSnapshot: async () => snapshot(),
        buildSections: () => [],
        createJob,
        resolvePreviousComments,
      }),
    ).rejects.toBeInstanceOf(NoWordSectionsError)
    expect(createJob).not.toHaveBeenCalled()
    expect(resolvePreviousComments).not.toHaveBeenCalled()
  })
})
