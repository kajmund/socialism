const PROP_PATH = /\/prop\/(\d{4})(?:\/(\d{2}))?:(\d+)(?:[#/?]|$)/i
const SOU_PATH = /\/sou\/(\d{4}):(\d+)(?:[#/?]|$)/i
const DS_PATH = /\/ds\/(\d{4}):(\d+)(?:[#/?]|$)/i
const BET_PATH = /\/bet\/(\d{4}\/\d{2}:[A-Za-z]+\d+)(?:[#/?]|$)/i
const NJA_PATH = /\/dom\/nja\/(\d{4})s(\d+)(?:[#/?]|$)/i
const SFS_PATH = /\/(\d{4}):(\d+)(?:[#/?]|$)/i
const HEADER_NOISE =
  /regeringens\s+proposition(?:\s+nr\.?\s*\d+(?:\s+år\s+\d+)?)?|prop\.\s*\d{4}(?:\/\d{2})?:\d+|sou\s+\d{4}:\d+|\bnr\.?\s*\d+\b|beslutad\s+den\s+\d{1,2}\s+\w+\s+\d{4}|\bm\.m\.\b/gi
const PROPOSITION_PREFIX = /^(?:regeringens\s+)?proposition(?:en)?\s+om\s+/i

export type LegalSourceDisplay = {
  title: string
  excerpt: string | null
}

function compact(value: string): string {
  return value.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim()
}

export function citationFromLagenNuUrl(url: string | null | undefined): string | null {
  if (!url) return null
  const prop = PROP_PATH.exec(url)
  if (prop) {
    return prop[2] ? `Prop. ${prop[1]}/${prop[2]}:${prop[3]}` : `Prop. ${prop[1]}:${prop[3]}`
  }
  const sou = SOU_PATH.exec(url)
  if (sou) return `SOU ${sou[1]}:${sou[2]}`
  const ds = DS_PATH.exec(url)
  if (ds) return `Ds ${ds[1]}:${ds[2]}`
  const bet = BET_PATH.exec(url)
  if (bet) return `Bet. ${bet[1]}`
  const nja = NJA_PATH.exec(url)
  if (nja) return `NJA ${nja[1]} s. ${nja[2]}`
  if (/\/(?:prop|sou|ds|bet|dir|dom|lr)\//i.test(url)) return null
  const sfs = SFS_PATH.exec(url)
  return sfs ? `SFS ${sfs[1]}:${sfs[2]}` : null
}

function shortDescriptive(title: string | null, citation: string | null): string | null {
  if (!title) return null
  let text = compact(title)
  text = text.replace(PROPOSITION_PREFIX, "")
  text = text.replace(/(?:\s*m\.m\.)+$/i, "").replace(/[ ;,.—-]+$/g, "")
  if (citation && text.toLocaleLowerCase() === citation.toLocaleLowerCase()) return null
  if (!text) return null
  return text.charAt(0).toLocaleUpperCase() + text.slice(1)
}

function citationAlreadyIn(citation: string, descriptive: string): boolean {
  if (descriptive.toLocaleLowerCase().includes(citation.toLocaleLowerCase())) return true
  const number = /(\d{4}(?:\/\d{2})?:\d+)$/.exec(citation)
  return Boolean(number && descriptive.includes(number[1]))
}

export function isLegalFrontMatter(
  excerpt: string | null | undefined,
  title: string | null | undefined,
): boolean {
  if (!excerpt || !compact(excerpt)) return true
  const cleaned = compact(excerpt)
  if (!HEADER_NOISE.test(cleaned)) return false
  HEADER_NOISE.lastIndex = 0
  let residual = cleaned.replace(HEADER_NOISE, " ")
  if (title) {
    residual = residual.replace(new RegExp(compact(title).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig"), " ")
    const short = shortDescriptive(title, null)
    if (short) {
      residual = residual.replace(new RegExp(short.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig"), " ")
    }
  }
  return compact(residual).length < 80
}

export function legalSourceDisplay(source: {
  title?: string | null
  excerpt?: string | null
  source_url?: string | null
  provider?: string | null
  source_type?: string | null
}): LegalSourceDisplay {
  const citation = citationFromLagenNuUrl(source.source_url)
  const descriptive = shortDescriptive(source.title ?? null, citation)
  const title =
    citation && descriptive && !citationAlreadyIn(citation, descriptive)
      ? `${citation} — ${descriptive}`
      : descriptive || citation || source.title || source.provider || source.source_type || ""
  const excerpt = isLegalFrontMatter(source.excerpt, source.title) ? null : source.excerpt
  return { title, excerpt: excerpt ? compact(excerpt) : null }
}
