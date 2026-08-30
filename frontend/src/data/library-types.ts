export type PersonaOrigin = "manuell" | "beskrivning" | "demografi" | "population"
export type PersonaKind = "persona" | "expert"

export type LibraryPersona = {
  id: string
  kind: PersonaKind
  name: string
  age: number | null
  occ: string
  district: string
  quote: string
  pops: string[]
  updated: string
  origin: PersonaOrigin
  profile: EditablePersona
  tools?: string[] | null
}

export type PopulationSummary = {
  id: number
  kind?: "persona" | "expert_panel"
  name: string
  size: number
  runs: number
  updated: string
  versions: number
  fp: number[][]
}

export type PopulationMember = {
  member_id?: number
  id?: string
  name: string
  initials: string
  age: number
  occ: string
  district: string
  trait: string
  persona_origin?: PersonaOrigin
}

export type EditablePersona = {
  name: string
  initials: string
  age: string
  kön: string
  ort: string
  yrke: string
  utbildning: string
  livssituation: string
  lutning: string
  sakfragor: string
  fortroende: string
  ton: string
  sprak: string
  medievanor: string
  parti: string
  valdeltagande: string
  anekdot?: string
  key?: number
  beskrivning?: string
  kompetensomrade?: string
  radgivningsstil?: string
  yrkesbakgrund?: string
  professionell_anekdot?: string
}
