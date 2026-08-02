import type {
  EditablePersona,
  LibraryPersona,
  PopulationMember,
} from "@/data/library-types"

export const ORIGIN_LABEL: Record<LibraryPersona["origin"], string> = {
  manuell: "Manuell",
  beskrivning: "Från beskrivning",
  demografi: "Från demografi",
  population: "Via population",
}

export const FP_COLORS = [
  "var(--db-ink-950)",
  "var(--db-gold-500)",
  "var(--db-ink-400)",
] as const

export const FP_DETAIL_LABELS = [
  ["Ung", "Medel", "Äldre"],
  ["Vänster", "Mitt", "Höger"],
  ["Centrum", "Distrikt A", "Övriga"],
] as const

export function personaInitials(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

export function formatLibraryDate(d: string): string {
  return new Date(d).toLocaleDateString("sv-SE", { day: "numeric", month: "short" })
}

export function blankEditablePersona(): EditablePersona {
  return {
    name: "Namnlös persona",
    initials: "--",
    age: "—",
    ort: "—",
    yrke: "—",
    utbildning: "—",
    livssituation: "—",
    lutning: "—",
    sakfragor: "—",
    fortroende: "—",
    ton: "—",
    sprak: "—",
    medievanor: "—",
    parti: "—",
    valdeltagande: "—",
  }
}

export function libraryPersonaToMember(p: LibraryPersona): PopulationMember {
  return {
    id: p.id,
    name: p.name,
    initials: personaInitials(p.name),
    age: p.age,
    occ: p.occ,
    district: p.district,
    trait: p.quote,
  }
}
