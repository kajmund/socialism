import { Fragment, type ReactNode } from "react"

/**
 * Lightweight chat markdown: headings, hr, **bold**, *italic*, newlines, lists.
 * No HTML passthrough — only React text nodes + tags.
 */
export function ChatMarkdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n")
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    if (isHrLine(line)) {
      blocks.push(<hr key={`hr-${key++}`} />)
      i += 1
      continue
    }

    const heading = matchHeading(line)
    if (heading) {
      const Tag = heading.tag
      blocks.push(
        <Tag key={`h-${key++}`} className={`chat-md-h chat-md-${heading.tag}`}>
          {renderInline(heading.text, `h-${key}`)}
        </Tag>,
      )
      i += 1
      continue
    }

    if (isBulletLine(line)) {
      const items: ReactNode[] = []
      while (i < lines.length && isBulletLine(lines[i])) {
        items.push(
          <li key={`li-${key++}`}>{renderInline(stripBullet(lines[i]), `i-${key}`)}</li>,
        )
        i += 1
      }
      blocks.push(<ul key={`ul-${key++}`}>{items}</ul>)
      continue
    }

    if (line.trim() === "") {
      i += 1
      continue
    }

    const para: string[] = [line]
    i += 1
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !isBulletLine(lines[i]) &&
      !isHrLine(lines[i]) &&
      !matchHeading(lines[i])
    ) {
      para.push(lines[i])
      i += 1
    }
    blocks.push(
      <p key={`p-${key++}`}>
        {para.map((row, idx) => (
          <Fragment key={`r-${key}-${idx}`}>
            {idx > 0 ? <br /> : null}
            {renderInline(row, `r-${key}-${idx}`)}
          </Fragment>
        ))}
      </p>,
    )
  }

  if (blocks.length === 0) return null
  return <>{blocks}</>
}

function isHrLine(line: string): boolean {
  return /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
}

function matchHeading(line: string): { tag: "h1" | "h2" | "h3" | "h4"; text: string } | null {
  const m = /^(#{1,4})\s+(.+?)\s*$/.exec(line)
  if (!m) return null
  const level = m[1].length as 1 | 2 | 3 | 4
  const tag = (`h${level}`) as "h1" | "h2" | "h3" | "h4"
  return { tag, text: m[2] }
}

function isBulletLine(line: string): boolean {
  return /^\s*[-*]\s+\S/.test(line)
}

function stripBullet(line: string): string {
  return line.replace(/^\s*[-*]\s+/, "")
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  // **bold** then *italic* — bold first so nested asterisks don't collide.
  const re = /\*\*(.+?)\*\*|\*(.+?)\*/g
  let last = 0
  let match: RegExpExecArray | null
  let n = 0
  while ((match = re.exec(text)) != null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index))
    }
    if (match[1] != null) {
      nodes.push(<strong key={`${keyPrefix}-b-${n++}`}>{match[1]}</strong>)
    } else if (match[2] != null) {
      nodes.push(<em key={`${keyPrefix}-e-${n++}`}>{match[2]}</em>)
    }
    last = match.index + match[0].length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}
