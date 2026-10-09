export type DocumentMention = {
  display_name: string
  source_object_id: string
}

const WORD = /[\p{L}\p{N}_]/u
const END_BOUNDARY = /[\s.,;:!?)]/u

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
