import { memo, useMemo, type ReactNode } from "react"

type AgentRow = {
  index: number
  member_name: string
}

export type MentionAlias = {
  userIds: number[]
  label: string
  variants: string[]
}

type Segment =
  | { kind: "text"; value: string }
  | { kind: "mention"; userIds: number[]; label: string }

type MentionTarget = {
  userIds: number[]
  label: string
}

type CompiledMatcher = {
  re: RegExp
  lookup: Map<string, MentionTarget>
}

const compiledMatcherCache = new Map<string, CompiledMatcher>()

function firstName(fullName: string): string {
  const token = fullName.trim().split(/\s+/)[0]
  return token || fullName.trim()
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** Build mention patterns from agent display names. */
export function buildMentionAliases(agents: AgentRow[]): MentionAlias[] {
  const withNames = agents.filter((a) => a.member_name.trim())
  const firstCounts = new Map<string, number>()
  for (const agent of withNames) {
    const key = firstName(agent.member_name).toLocaleLowerCase("sv-SE")
    firstCounts.set(key, (firstCounts.get(key) ?? 0) + 1)
  }

  const byKey = new Map<string, MentionAlias>()

  const addVariant = (raw: string, userId: number, label: string) => {
    const key = raw.toLocaleLowerCase("sv-SE")
    const existing = byKey.get(key)
    if (existing) {
      if (!existing.userIds.includes(userId)) existing.userIds.push(userId)
      return
    }
    byKey.set(key, { userIds: [userId], label, variants: [raw] })
  }

  for (const agent of withNames) {
    const full = agent.member_name.trim()
    const first = firstName(full)
    const label = `@${first}`
    addVariant(full, agent.index, label)
    addVariant(`@${full}`, agent.index, label)
    addVariant(`@${first}`, agent.index, label)
    if ((firstCounts.get(first.toLocaleLowerCase("sv-SE")) ?? 0) === 1) {
      addVariant(first, agent.index, label)
    }
  }

  return [...byKey.values()].sort(
    (a, b) =>
      Math.max(...b.variants.map((v) => v.length)) -
      Math.max(...a.variants.map((v) => v.length)),
  )
}

function matcherCacheKey(aliases: MentionAlias[]): string {
  return aliases
    .map(
      (alias) =>
        `${alias.userIds.join(",")}:${alias.label}:${alias.variants.join("|")}`,
    )
    .join(";")
}

export function getMentionMatcher(aliases: MentionAlias[]): CompiledMatcher | null {
  if (aliases.length === 0) return null
  const key = matcherCacheKey(aliases)
  const cached = compiledMatcherCache.get(key)
  if (cached) return cached

  const lookup = new Map<string, MentionTarget>()
  const patterns: string[] = []

  for (const alias of aliases) {
    for (const raw of alias.variants) {
      const lookupKey = raw.toLocaleLowerCase("sv-SE")
      const existing = lookup.get(lookupKey)
      if (existing) {
        for (const userId of alias.userIds) {
          if (!existing.userIds.includes(userId)) existing.userIds.push(userId)
        }
        continue
      }
      lookup.set(lookupKey, {
        userIds: [...alias.userIds],
        label: alias.label,
      })
      patterns.push(escapeRegex(raw))
    }
  }

  if (patterns.length === 0) return null

  patterns.sort((a, b) => b.length - a.length)
  const matcher: CompiledMatcher = {
    re: new RegExp(
      `(?<![\\p{L}\\p{N}_])(${patterns.join("|")})(?![\\p{L}\\p{N}_])`,
      "giu",
    ),
    lookup,
  }
  compiledMatcherCache.set(key, matcher)
  return matcher
}

function parseMentionSegments(
  text: string,
  matcher: CompiledMatcher | null,
): Segment[] {
  if (!text) return [{ kind: "text", value: "" }]
  if (!matcher) return [{ kind: "text", value: text }]

  const segments: Segment[] = []
  let last = 0
  matcher.re.lastIndex = 0

  for (;;) {
    const match = matcher.re.exec(text)
    if (!match) break
    const start = match.index
    const matched = match[0]
    const meta = matcher.lookup.get(matched.toLocaleLowerCase("sv-SE"))
    if (!meta) continue

    if (start > last) {
      segments.push({ kind: "text", value: text.slice(last, start) })
    }
    segments.push({
      kind: "mention",
      userIds: meta.userIds,
      label: meta.label,
    })
    last = start + matched.length
  }

  if (last < text.length) {
    segments.push({ kind: "text", value: text.slice(last) })
  }
  return segments.length > 0 ? segments : [{ kind: "text", value: text }]
}

export const CommentBody = memo(function CommentBody({
  text,
  matcher,
  onOpenMention,
  className,
}: {
  text: string
  matcher: CompiledMatcher | null
  onOpenMention: (userIds: number[], label: string) => void
  className?: string
}) {
  const segments = useMemo(
    () => parseMentionSegments(text, matcher),
    [text, matcher],
  )

  const nodes: ReactNode[] = useMemo(
    () =>
      segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <span key={`t-${index}`}>{segment.value}</span>
        }
        return (
          <button
            key={`m-${index}-${segment.userIds.join("-")}`}
            type="button"
            className="font-medium text-foreground underline-offset-2 hover:underline"
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              onOpenMention(segment.userIds, segment.label)
            }}
          >
            {segment.label}
          </button>
        )
      }),
    [segments, onOpenMention],
  )

  return <p className={className}>{nodes}</p>
})
