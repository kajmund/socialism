import type {
  DdResearchPerson,
  DdResearchPersonCompany,
  DdResearchPersonSeat,
} from "@/api/dd"

export function allabolagSearchUrl(orgnr: string, namn: string): string {
  const digits = orgnr.replace(/\D/g, "")
  const query = digits.length === 10 ? digits : namn.trim()
  return `https://www.allabolag.se/bransch-s%C3%B6k?q=${encodeURIComponent(query || namn)}`
}

const PEOPLE_LEFTOVER_PREFIXES = [
  "Kvar att kartlägga:",
  "Fler uppdrag:",
  "Webbsök:",
  "Inga bolag för person:",
  "Kap: hoppade person",
  "Personen finns inte i koncernlistan:",
] as const

export function leftoverMisses(items: string[]): string[] {
  return items.filter(
    (item) => !PEOPLE_LEFTOVER_PREFIXES.some((prefix) => item.startsWith(prefix)),
  )
}

export function appointmentCapNote(leftover: string[], name: string): string | undefined {
  return leftover.find((item) => item.startsWith(`Fler uppdrag: ${name}`))
}

export function groupedSeats(
  poster: DdResearchPersonSeat[],
): { namn: string; orgnr: string; rolls: string[] }[] {
  const groups: { namn: string; orgnr: string; rolls: string[] }[] = []
  const index = new Map<string, number>()
  for (const seat of poster) {
    const key = seat.orgnr || seat.namn
    let at = index.get(key)
    if (at === undefined) {
      at = groups.length
      index.set(key, at)
      groups.push({ namn: seat.namn, orgnr: seat.orgnr, rolls: [] })
    }
    if (seat.roll && !groups[at].rolls.includes(seat.roll)) {
      groups[at].rolls.push(seat.roll)
    }
  }
  return groups
}

export function formatSeats(poster: DdResearchPersonSeat[]): string {
  return groupedSeats(poster)
    .map((row) => (row.rolls.length ? `${row.namn} (${row.rolls.join(", ")})` : row.namn))
    .join(", ")
}

export function formatAppointments(bolag: DdResearchPersonCompany[]): string {
  return bolag.map((row) => (row.orgnr ? `${row.namn} (${row.orgnr})` : row.namn)).join(", ")
}

export function isAuditorRole(roll: string): boolean {
  return roll.toLowerCase().includes("revisor")
}

export function personIsAuditor(person: {
  roll: string
  poster: { roll: string }[]
}): boolean {
  return isAuditorRole(person.roll) || person.poster.some((seat) => isAuditorRole(seat.roll))
}

export function sortPeopleAuditorsLast<
  T extends { namn: string; roll: string; poster: { roll: string }[] },
>(people: T[]): T[] {
  return [...people].sort((a, b) => {
    const byAuditor = Number(personIsAuditor(a)) - Number(personIsAuditor(b))
    return byAuditor !== 0 ? byAuditor : a.namn.localeCompare(b.namn, "sv")
  })
}

export function personInvestigated(person: DdResearchPerson): boolean {
  return person.bolag.length > 0 || person.web_hits.some((hit) => Boolean(hit.url))
}

export function personInitials(namn: string): string {
  const parts = namn.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  const first = parts[0][0] ?? ""
  const last = parts[parts.length - 1][0] ?? ""
  return `${first}${last}`.toUpperCase()
}

/** Role counts from in-group board seats (poster). */
export function roleSummaryParts(
  person: DdResearchPerson,
): { roll: string; count: number }[] {
  const byRole = new Map<string, Set<string>>()
  for (const seat of person.poster) {
    const roll = (seat.roll || person.roll || "").trim()
    if (!roll) continue
    const key = seat.orgnr || seat.namn
    let companies = byRole.get(roll)
    if (!companies) {
      companies = new Set()
      byRole.set(roll, companies)
    }
    companies.add(key)
  }
  if (byRole.size === 0 && person.roll.trim()) {
    return [{ roll: person.roll.trim(), count: 0 }]
  }
  return [...byRole.entries()].map(([roll, companies]) => ({
    roll,
    count: companies.size,
  }))
}

export type AppointmentBreakdown = {
  inGroup: { namn: string; orgnr: string; rolls: string[] }[]
  outside: DdResearchPersonCompany[]
  inGroupCount: number
  outsideCount: number
}

export function appointmentBreakdown(
  person: DdResearchPerson,
  groupOrgnr: Set<string>,
): AppointmentBreakdown {
  const inGroup = groupedSeats(person.poster)
  if (person.bolag.length === 0) {
    return {
      inGroup,
      outside: [],
      inGroupCount: inGroup.length,
      outsideCount: 0,
    }
  }
  const outside = person.bolag.filter((row) => !row.orgnr || !groupOrgnr.has(row.orgnr))
  const inFromBolag = person.bolag.filter((row) => Boolean(row.orgnr && groupOrgnr.has(row.orgnr)))
  const inGroupCount =
    inFromBolag.length > 0
      ? new Set(inFromBolag.map((row) => row.orgnr)).size
      : inGroup.length
  return {
    inGroup,
    outside,
    inGroupCount,
    outsideCount: outside.length,
  }
}

export function matchesPersonSearch(person: DdResearchPerson, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (person.namn.toLowerCase().includes(q)) return true
  if (person.roll.toLowerCase().includes(q)) return true
  if (
    person.poster.some(
      (seat) =>
        seat.namn.toLowerCase().includes(q) ||
        seat.roll.toLowerCase().includes(q) ||
        seat.orgnr.includes(q),
    )
  ) {
    return true
  }
  return person.bolag.some(
    (row) => row.namn.toLowerCase().includes(q) || row.orgnr.includes(q),
  )
}

export type PeopleFilter = "all" | "notInvestigated"

export function filterPeople(
  people: DdResearchPerson[],
  query: string,
  filter: PeopleFilter,
): DdResearchPerson[] {
  return people.filter((person) => {
    if (filter === "notInvestigated" && personInvestigated(person)) return false
    return matchesPersonSearch(person, query)
  })
}
