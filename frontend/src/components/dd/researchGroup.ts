import type { DdResearchCompany, DdResearchPerson } from "@/api/dd"
import { groupedSeats } from "@/components/dd/researchPeople"

export type GroupCompanyFilter = "all" | "withFigures" | "withoutFigures" | "negativeResult"

export type CompanyFigures = {
  omsattningSek: number | null
  anstallda: number | null
  resultatSek: number | null
  resultatYear: string | null
}

export type GroupKpis = {
  companyCount: number
  levels: number
  midHoldings: number
  omsattningSek: number | null
  omsattningCount: number
  anstallda: number | null
  anstalldaMaxName: string | null
  anstalldaMax: number | null
  resultatSek: number | null
  resultatDriverName: string | null
  resultatDriverSek: number | null
  withoutFigures: number
}

export function companyKey(company: DdResearchCompany): string {
  return company.orgnr || `name:${company.namn}`
}

export function childrenOf(
  companies: DdResearchCompany[],
  parentOrgnr: string,
): DdResearchCompany[] {
  if (!parentOrgnr) return []
  return companies
    .filter((row) => (row.parent_orgnr || "") === parentOrgnr)
    .sort((a, b) => a.namn.localeCompare(b.namn, "sv"))
}

export function rootCompanies(companies: DdResearchCompany[]): DdResearchCompany[] {
  const orgnrs = new Set(companies.map((row) => row.orgnr).filter(Boolean))
  const roots = companies.filter(
    (row) => !row.parent_orgnr || !orgnrs.has(row.parent_orgnr),
  )
  const ordered = roots.length > 0 ? roots : companies.slice(0, 1)
  return [...ordered].sort((a, b) => {
    const rank = (row: DdResearchCompany) =>
      row.relation === "moderbolag" ? 0 : row.relation === "kandidat" ? 1 : 2
    const byRelation = rank(a) - rank(b)
    return byRelation !== 0 ? byRelation : a.namn.localeCompare(b.namn, "sv")
  })
}

function parseSekAmount(raw: string): number | null {
  const cleaned = raw.replace(/\s/g, "").replace(/SEK/gi, "").replace(/,/g, "")
  if (!cleaned || cleaned === "-") return null
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : null
}

export function parseCompanyFigures(nyckeltal: string[]): CompanyFigures {
  let omsattningSek: number | null = null
  let anstallda: number | null = null
  let resultatSek: number | null = null
  let resultatYear: string | null = null
  for (const line of nyckeltal) {
    const oms = /^Omsättning:\s*(.+)$/i.exec(line)
    if (oms) {
      omsattningSek = parseSekAmount(oms[1])
      continue
    }
    const emp = /^Anställda:\s*(\d+)/i.exec(line)
    if (emp) {
      anstallda = Number(emp[1])
      continue
    }
    const res = /^Resultat(?:\s+(\d{4}))?:\s*(.+)$/i.exec(line)
    if (res) {
      resultatYear = res[1] ?? null
      resultatSek = parseSekAmount(res[2])
    }
  }
  return { omsattningSek, anstallda, resultatSek, resultatYear }
}

export function hasFigures(figures: CompanyFigures): boolean {
  return (
    figures.omsattningSek != null ||
    figures.anstallda != null ||
    figures.resultatSek != null
  )
}

/** Compact SEK: 728 Mkr, 30,2 Mkr, -316 tkr, 0 kr */
export function formatCompactSek(sek: number | null | undefined): string {
  if (sek == null || !Number.isFinite(sek)) return "—"
  const abs = Math.abs(sek)
  const sign = sek < 0 ? "-" : ""
  if (abs >= 1_000_000) {
    const mkr = abs / 1_000_000
    const rounded = mkr >= 100 ? Math.round(mkr).toString() : mkr.toFixed(1).replace(".", ",")
    return `${sign}${rounded.replace(/,0$/, "")} Mkr`
  }
  if (abs >= 1_000) {
    const tkr = Math.round(abs / 1_000)
    return `${sign}${tkr.toLocaleString("sv-SE")} tkr`
  }
  return `${sign}${Math.round(abs).toLocaleString("sv-SE")} kr`
}

export function formatCompactEmployees(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—"
  return n.toLocaleString("sv-SE")
}

export function percentOf(part: number | null, total: number | null): number | null {
  if (part == null || total == null || total === 0) return null
  return Math.round((part / total) * 100)
}

export function companyLevel(
  company: DdResearchCompany,
  byOrgnr: Map<string, DdResearchCompany>,
): number {
  let level = 1
  let parent = company.parent_orgnr ? byOrgnr.get(company.parent_orgnr) : undefined
  const seen = new Set<string>()
  while (parent) {
    const key = companyKey(parent)
    if (seen.has(key)) break
    seen.add(key)
    level += 1
    parent = parent.parent_orgnr ? byOrgnr.get(parent.parent_orgnr) : undefined
  }
  return level
}

export function descendantCount(
  companies: DdResearchCompany[],
  company: DdResearchCompany,
): number {
  if (!company.orgnr) return 0
  const seen = new Set<string>()
  const stack = childrenOf(companies, company.orgnr)
  let count = 0
  while (stack.length > 0) {
    const next = stack.pop()!
    const key = companyKey(next)
    if (seen.has(key)) continue
    seen.add(key)
    count += 1
    if (next.orgnr) stack.push(...childrenOf(companies, next.orgnr))
  }
  return count
}

export function computeGroupKpis(companies: DdResearchCompany[]): GroupKpis {
  const byOrgnr = new Map(
    companies.filter((row) => row.orgnr).map((row) => [row.orgnr, row]),
  )
  let levels = 0
  let midHoldings = 0
  let omsattningSek: number | null = null
  let omsattningCount = 0
  let anstallda: number | null = null
  let anstalldaMax: number | null = null
  let anstalldaMaxName: string | null = null
  let resultatSek: number | null = null
  let resultatDriverSek: number | null = null
  let resultatDriverName: string | null = null
  let withoutFigures = 0

  for (const company of companies) {
    const figures = parseCompanyFigures(company.nyckeltal)
    levels = Math.max(levels, companyLevel(company, byOrgnr))
    const kids = company.orgnr ? childrenOf(companies, company.orgnr).length : 0
    if (company.parent_orgnr && kids > 0) midHoldings += 1

    if (!hasFigures(figures)) withoutFigures += 1

    if (figures.omsattningSek != null) {
      omsattningSek = (omsattningSek ?? 0) + figures.omsattningSek
      omsattningCount += 1
    }
    if (figures.anstallda != null) {
      anstallda = (anstallda ?? 0) + figures.anstallda
      if (anstalldaMax == null || figures.anstallda > anstalldaMax) {
        anstalldaMax = figures.anstallda
        anstalldaMaxName = company.namn
      }
    }
    if (figures.resultatSek != null) {
      resultatSek = (resultatSek ?? 0) + figures.resultatSek
      if (resultatDriverSek == null || figures.resultatSek < resultatDriverSek) {
        resultatDriverSek = figures.resultatSek
        resultatDriverName = company.namn
      }
    }
  }

  return {
    companyCount: companies.length,
    levels,
    midHoldings,
    omsattningSek,
    omsattningCount,
    anstallda,
    anstalldaMaxName,
    anstalldaMax,
    resultatSek,
    resultatDriverName,
    resultatDriverSek,
    withoutFigures,
  }
}

function companyMatchesQuery(
  company: DdResearchCompany,
  query: string,
  people: DdResearchPerson[],
): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (company.namn.toLowerCase().includes(q)) return true
  if (company.orgnr.toLowerCase().includes(q)) return true
  if (company.styrelse.some((row) => row.toLowerCase().includes(q))) return true
  return people.some(
    (person) =>
      person.namn.toLowerCase().includes(q) &&
      person.poster.some(
        (seat) =>
          (seat.orgnr && seat.orgnr === company.orgnr) ||
          seat.namn.toLowerCase() === company.namn.toLowerCase(),
      ),
  )
}

function companyMatchesFilter(
  company: DdResearchCompany,
  filter: GroupCompanyFilter,
): boolean {
  if (filter === "all") return true
  const figures = parseCompanyFigures(company.nyckeltal)
  switch (filter) {
    case "withFigures":
      return hasFigures(figures)
    case "withoutFigures":
      return !hasFigures(figures)
    case "negativeResult":
      return figures.resultatSek != null && figures.resultatSek < 0
    default: {
      const _exhaustive: never = filter
      return _exhaustive
    }
  }
}

/** Matches plus ancestors so the tree hierarchy stays intact. */
export function filterGroupCompanies(
  companies: DdResearchCompany[],
  query: string,
  filter: GroupCompanyFilter,
  people: DdResearchPerson[],
): DdResearchCompany[] {
  const byOrgnr = new Map(
    companies.filter((row) => row.orgnr).map((row) => [row.orgnr, row]),
  )
  const keep = new Set<string>()
  for (const company of companies) {
    if (!companyMatchesQuery(company, query, people)) continue
    if (!companyMatchesFilter(company, filter)) continue
    keep.add(companyKey(company))
    let parent = company.parent_orgnr ? byOrgnr.get(company.parent_orgnr) : undefined
    const seen = new Set<string>()
    while (parent) {
      const key = companyKey(parent)
      if (seen.has(key)) break
      seen.add(key)
      keep.add(key)
      parent = parent.parent_orgnr ? byOrgnr.get(parent.parent_orgnr) : undefined
    }
  }
  return companies.filter((row) => keep.has(companyKey(row)))
}

export function findParent(
  companies: DdResearchCompany[],
  company: DdResearchCompany,
): DdResearchCompany | null {
  if (!company.parent_orgnr) return null
  return companies.find((row) => row.orgnr === company.parent_orgnr) ?? null
}

export function findModerbolag(companies: DdResearchCompany[]): DdResearchCompany | null {
  return companies.find((row) => row.relation === "moderbolag") ?? rootCompanies(companies)[0] ?? null
}

export function findKandidat(companies: DdResearchCompany[]): DdResearchCompany | null {
  return companies.find((row) => row.relation === "kandidat") ?? null
}

/** Keys of ancestors on the path to the candidate so the path is expanded. */
export function defaultExpandedKeys(companies: DdResearchCompany[]): Set<string> {
  const expanded = new Set<string>()
  const kandidat = findKandidat(companies)
  const byOrgnr = new Map(
    companies.filter((row) => row.orgnr).map((row) => [row.orgnr, row]),
  )
  for (const root of rootCompanies(companies)) {
    expanded.add(companyKey(root))
  }
  if (!kandidat) return expanded
  let current: DdResearchCompany | undefined = kandidat
  const seen = new Set<string>()
  while (current) {
    const key = companyKey(current)
    if (seen.has(key)) break
    seen.add(key)
    if (current.parent_orgnr) {
      const parent = byOrgnr.get(current.parent_orgnr)
      if (parent) expanded.add(companyKey(parent))
    }
    current = current.parent_orgnr ? byOrgnr.get(current.parent_orgnr) : undefined
  }
  return expanded
}

export type BoardSeatRow = {
  namn: string
  rolls: string[]
  companyCount: number
  initials: string
}

function parseStyrelseLine(line: string): { namn: string; roll: string } {
  const match = /^(.+?)\s*\(([^)]+)\)\s*$/.exec(line.trim())
  if (match) return { namn: match[1].trim(), roll: match[2].trim() }
  return { namn: line.trim(), roll: "" }
}

export function boardRowsForCompany(
  company: DdResearchCompany,
  people: DdResearchPerson[],
  _groupSize: number,
  initialsOf: (namn: string) => string,
): BoardSeatRow[] {
  const fromPeople = people
    .map((person) => {
      const seats = person.poster.filter(
        (seat) =>
          (seat.orgnr && seat.orgnr === company.orgnr) ||
          (!seat.orgnr && seat.namn.toLowerCase() === company.namn.toLowerCase()),
      )
      if (seats.length === 0) return null
      const rolls = [
        ...new Set(seats.map((seat) => seat.roll).filter(Boolean)),
      ]
      const inGroup = groupedSeats(person.poster).length
      return {
        namn: person.namn,
        rolls,
        companyCount: inGroup > 0 ? inGroup : 1,
        initials: initialsOf(person.namn),
      }
    })
    .filter((row): row is BoardSeatRow => row != null)

  if (fromPeople.length > 0) return fromPeople

  const byName = new Map<string, BoardSeatRow>()
  for (const line of company.styrelse) {
    const { namn, roll } = parseStyrelseLine(line)
    if (!namn) continue
    const key = namn.toLowerCase()
    const existing = byName.get(key)
    if (existing) {
      if (roll && !existing.rolls.includes(roll)) existing.rolls.push(roll)
      continue
    }
    byName.set(key, {
      namn,
      rolls: roll ? [roll] : [],
      companyCount: 1,
      initials: initialsOf(namn),
    })
  }
  return [...byName.values()]
}
