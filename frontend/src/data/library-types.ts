export type PersonaOrigin = "manuell" | "beskrivning" | "demografi" | "population"

export type LibraryPersona = {
  id: string
  name: string
  age: number
  occ: string
  district: string
  quote: string
  pops: string[]
  updated: string
  origin: PersonaOrigin
}

export type PopulationSummary = {
  id: number
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
}

export type EditablePersona = {
  name: string
  initials: string
  age: string
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
  key?: number
}
