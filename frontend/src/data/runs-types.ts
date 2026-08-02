export type RunStatus = "done" | "running" | "draft" | "failed"

export type OasisRunResults = {
  engine?: string
  error?: string
  ticks_run?: number
  agents?: Array<{
    index: number
    username: string
    member_name: string
    persona_id: string | null
  }>
  posts?: Array<{
    post_id: number
    user_id: number
    content: string
    num_likes: number
    num_dislikes?: number
    num_shares?: number
    created_at?: string
  }>
  comments?: Array<{
    comment_id: number
    post_id: number
    user_id: number
    content: string
    num_likes?: number
  }>
  artifact_db?: string
}

export type RunSummary = {
  id: number
  name: string
  status: RunStatus
  population: string
  ticks: number
  variants: number
  seed: string
  updated: string
}

export type RunPopulationOption = {
  id: number
  name: string
  size: number
  initials: string[]
}

export type InjectionType = "party_post" | "news_post" | "ad_post"
export type InjectionMode = "text" | "link"

export type Injection = {
  key: string
  type: InjectionType
  sender: string
  text: string
  mode: InjectionMode
  url: string
  fetching: boolean
  sourceDomain: string
  isVideo: boolean
}

export type Tick = {
  key: string
  day: number
  silent: boolean
  injections: Injection[]
  rounds: number
  measurements: string[]
}

export type BranchState = {
  afterIndex: number
  a: Tick[]
  b: Tick[]
}

export type Measurement = {
  id: string
  label: string
}
