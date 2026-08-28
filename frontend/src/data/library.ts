import type {
  EditablePersona,
  LibraryPersona,
  PersonaOrigin,
  PopulationMember,
} from "@/data/library-types"
import type { MessageKey, TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

/** Persona origin badge label — cards/rows show the short "via population" form. */
export function originLabel(origin: PersonaOrigin, t: Translate): string {
  switch (origin) {
    case "manuell":
      return t("personas.origin.manual")
    case "beskrivning":
      return t("personas.origin.fromDescription")
    case "demografi":
      return t("personas.origin.fromDemographics")
    case "population":
      return t("personas.origin.viaPopulation")
    default: {
      const exhaustive: never = origin
      return exhaustive
    }
  }
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

export function formatLibraryDate(d: string, locale = "sv-SE"): string {
  return new Date(d).toLocaleDateString(locale, { day: "numeric", month: "short" })
}

export function personaAnekdot(
  profile: Pick<EditablePersona, "anekdot">,
): string | null {
  const value = profile.anekdot?.trim()
  if (!value || value === "—") return null
  return value
}

export function blankEditablePersona(): EditablePersona {
  return {
    name: "Namnlös persona",
    initials: "--",
    age: "—",
    kön: "—",
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
    anekdot: "—",
  }
}

export function blankEditableExpert(): EditablePersona {
  return {
    ...blankEditablePersona(),
    name: "Namnlös expert",
    age: "—",
    beskrivning: "—",
    kompetensomrade: "—",
    radgivningsstil: "—",
    yrkesbakgrund: "—",
    professionell_anekdot: "—",
  }
}

export function libraryPersonaToMember(p: LibraryPersona): PopulationMember {
  return {
    id: p.id,
    name: p.name,
    initials: personaInitials(p.name),
    age: p.age ?? 0,
    occ: p.occ,
    district: p.district,
    trait: p.quote,
  }
}
