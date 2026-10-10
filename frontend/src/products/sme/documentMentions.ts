export type DocumentMention = {
  display_name: string
  source_object_id: string
}

const WORD = /[\p{L}\p{N}_]/u
const END_BOUNDARY = /[\s.,;:!?)]/u

export function activeDocumentQuery(
  message: string,
  caret: number,
): { start: number; query: string } | null {
  const head = message.slice(0, caret)
  for (let index = head.length - 1; index >= 0; index -= 1) {
    const char = head[index] ?? ""
    if (char === "\n") return null
    if (char !== "@") continue
    const before = index > 0 ? head[index - 1] ?? "" : ""
    if (before && WORD.test(before)) return null
    return { start: index, query: head.slice(index + 1) }
  }
  return null
}

export function documentMentionChoices(
  files: { id: string; filename: string }[],
  query: string,
): { id: string; filename: string }[] {
  const unique = files.filter(
    (file) => files.filter((candidate) => candidate.filename === file.filename).length === 1,
  )
  const needle = query.toLocaleLowerCase("sv-SE")
  return unique
    .filter((file) => !needle || file.filename.toLocaleLowerCase("sv-SE").includes(needle))
    .sort((left, right) => {
      const leftName = left.filename.toLocaleLowerCase("sv-SE")
      const rightName = right.filename.toLocaleLowerCase("sv-SE")
      const leftRank = needle && leftName.startsWith(needle) ? 0 : 1
      const rightRank = needle && rightName.startsWith(needle) ? 0 : 1
      return leftRank - rightRank || leftName.localeCompare(rightName, "sv")
    })
}

export function insertDocumentMention(
  message: string,
  caret: number,
  filename: string,
): { text: string; caret: number } | null {
  const active = activeDocumentQuery(message, caret)
  if (!active) return null
  const insertion = `@${filename} `
  return {
    text: message.slice(0, active.start) + insertion + message.slice(caret),
    caret: active.start + insertion.length,
  }
}

export function resolveDocumentMentions(
  message: string,
  files: { id: string; filename: string }[],
): DocumentMention[] {
  const mentions: DocumentMention[] = []
  const seen = new Set<string>()
  const unique = files.filter(
    (file) => files.filter((candidate) => candidate.filename === file.filename).length === 1,
  )
  const matches = unique.flatMap((file) => {
    const needle = `@${file.filename}`
    const positions: number[] = []
    let from = 0
    while (from < message.length) {
      const index = message.indexOf(needle, from)
      if (index < 0) break
      const before = index > 0 ? message[index - 1] : ""
      const after = message[index + needle.length] ?? ""
      if ((!before || !WORD.test(before)) && (!after || END_BOUNDARY.test(after))) {
        positions.push(index)
      }
      from = index + needle.length
    }
    return positions.map((index) => ({ file, index }))
  }).sort((left, right) => left.index - right.index || right.file.filename.length - left.file.filename.length)
  let previousIndex = -1
  for (const { file, index } of matches) {
    if (index === previousIndex) continue
    previousIndex = index
    if (!file || seen.has(file.id)) continue
    seen.add(file.id)
    mentions.push({ display_name: file.filename, source_object_id: file.id })
  }
  return mentions
}
