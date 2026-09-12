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

export async function startNewWordReview(args: {
  captureSnapshot: () => Promise<WordTaskSnapshot>
  buildSections: (paragraphs: WordParagraph[]) => WordDocumentSection[]
  createJob: (input: {
    snapshot: WordTaskSnapshot
    sections: WordDocumentSection[]
  }) => Promise<string>
  resolvePreviousComments: () => Promise<void>
}): Promise<string> {
  const snapshot = await args.captureSnapshot()
  if (snapshot.paragraphs.length === 0) {
    throw new NoWordParagraphsError()
  }
  const sections = args.buildSections(snapshot.paragraphs)
  if (sections.length === 0) {
    throw new NoWordSectionsError()
  }
  const jobId = await args.createJob({ snapshot, sections })
  await args.resolvePreviousComments()
  return jobId
}
