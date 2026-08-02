export type PopulationStat = { n: string; l: string }

export type PopulationDistribution = {
  label: string
  pct: number
  color: string
}

export type Population = {
  id: string
  tag: string
  name: string
  desc: string
  n: number
  distribution: PopulationDistribution[]
  stats: PopulationStat[]
}

export type PersonaReaction = {
  tone: string
  text: string
  action: string
}

export type Persona = {
  name: string
  age: number
  occupation: string
  district: string
  party: string
  leaning: string
  initials: string
  color: string
  traits: string[]
  style: string
  quote: string
  knows?: string[]
  reactA: PersonaReaction
  reactB: PersonaReaction
}

export type MessageProfileTopPersona = {
  who: string
  initials: string
  color: string
  v: number
}

export type MessageProfile = {
  label: string
  style: string
  color: string
  excerpt: string
  avgEngagement: number
  reach: number
  sharedBy: number
  dominantTopic: string
  characteristicQuote: string
  characteristicWho: string
  audience: string
  topPersonas: MessageProfileTopPersona[]
  drift: number[]
  driftSecondary: { name: string; values: number[]; color: string }
}

export type District = {
  id: string
  name: string
  pop: number
  engA: number
  engB: number
  persona: string | null
}

export type TimeOption = { id: string; label: string; desc: string }
export type NewsOption = { id: string; label: string; desc: string }
