import type { WordDocumentSection, WordParagraph } from "@/lib/types"
import type { WordTaskSnapshot } from "@/lib/word/taskSnapshot"

export class NoWordParagraphsError extends Error {
  override name = "NoWordParagraphsError"
  constructor() {
    super("no_paragraphs")
  }
}

export class NoWordSectionsError extends Error {
  override name = "NoWordSectionsError"
  constructor() {
    super("no_sections")
  }
}

export async function prepareWordReview(args: {
  captureSnapshot: () => Promise<WordTaskSnapshot>
  buildSections: (paragraphs: WordParagraph[]) => WordDocumentSection[]
}): Promise<{ snapshot: WordTaskSnapshot; sections: WordDocumentSection[] }> {
  const snapshot = await args.captureSnapshot()
  if (snapshot.paragraphs.length === 0) {
    throw new NoWordParagraphsError()
  }
  const sections = args.buildSections(snapshot.paragraphs)
  if (sections.length === 0) {
    throw new NoWordSectionsError()
  }
  return { snapshot, sections }
}

export async function submitPreparedWordReview(args: {
  snapshot: WordTaskSnapshot
  sections: WordDocumentSection[]
  createJob: (input: {
    snapshot: WordTaskSnapshot
    sections: WordDocumentSection[]
  }) => Promise<string>
  resolvePreviousComments: () => Promise<void>
}): Promise<string> {
  const jobId = await args.createJob({
    snapshot: args.snapshot,
    sections: args.sections,
  })
  await args.resolvePreviousComments()
  return jobId
}

export async function startNewWordReview(args: {
  captureSnapshot: () => Promise<WordTaskSnapshot>
  buildSections: (paragraphs: WordParagraph[]) => WordDocumentSection[]
  createJob: (input: {
    snapshot: WordTaskSnapshot
    sections: WordDocumentSection[]
  }) => Promise<string>
  resolvePreviousComments: () => Promise<void>
}): Promise<string> {
  const prepared = await prepareWordReview(args)
  return submitPreparedWordReview({
    snapshot: prepared.snapshot,
    sections: prepared.sections,
    createJob: args.createJob,
    resolvePreviousComments: args.resolvePreviousComments,
  })
}
