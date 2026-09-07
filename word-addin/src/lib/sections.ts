import type { WordDocumentSection, WordParagraph } from "@/lib/types"

const HEADING_1 = /^(heading|rubrik)\s*1$/i

export function isHeading1(style: string): boolean {
  return HEADING_1.test(style.trim())
}

/**
 * Split raw Word paragraphs into sections on Heading 1 / Rubrik 1.
 * H2–H3 stay as raw paragraphs inside the current section so the server
 * can use them for heading assessment without treating them as new jobs.
 */
export function buildSections(paragraphs: WordParagraph[]): WordDocumentSection[] {
  const sections: WordDocumentSection[] = []
  let current: WordDocumentSection | null = null

  for (const paragraph of paragraphs) {
    if (isHeading1(paragraph.style)) {
      current = {
        heading: paragraph.text,
        heading_style: paragraph.style,
        heading_paragraph_index: paragraph.index,
        paragraphs: [],
      }
      sections.push(current)
      continue
    }
    if (current === null) {
      current = {
        heading: "",
        heading_style: "",
        heading_paragraph_index: paragraph.index,
        paragraphs: [],
      }
      sections.push(current)
    }
    current.paragraphs.push(paragraph)
  }

  return sections
}
