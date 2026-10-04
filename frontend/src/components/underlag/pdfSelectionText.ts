export type PdfSelectionFragment = {
  text: string
  x: number
  y: number
  width: number
}

// Positions are PDF points, matching the original text extractor's line/word tolerance.
export function pdfSelectionText(fragments: PdfSelectionFragment[]): string {
  const lines: { y: number; fragments: PdfSelectionFragment[] }[] = []
  for (const fragment of [...fragments].sort((a, b) => a.y - b.y || a.x - b.x)) {
    if (!fragment.text) continue
    let line = lines.find((row) => Math.abs(row.y - fragment.y) <= 3)
    if (!line) { line = { y: fragment.y, fragments: [] }; lines.push(line) }
    line.fragments.push(fragment)
  }
  return lines.map((line) => {
    let text = "", right: number | null = null
    for (const fragment of line.fragments.sort((a, b) => a.x - b.x)) {
      if (right !== null && fragment.x - right > 3) text += " "
      text += fragment.text
      right = fragment.x + fragment.width
    }
    return text
  }).join(" ").split(/\s+/).join(" ").trim()
}
