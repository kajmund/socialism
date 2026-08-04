export type RunStatus = "done" | "running" | "draft" | "failed"

export type OasisMeasurementPoint = {
  id: string
  label: string
  summary: string
  metrics?: {
    engagement?: {
      posts?: number
      comments?: number
      likes?: number
      shares?: number
      dislikes?: number
      engagement_score?: number
    }
    sentiment?: {
      positive?: number
      neutral?: number
      negative?: number
    }
    top_phrases?: Array<{ phrase: string; count: number }>
    by_district?: Array<{
      label: string
      posts?: number
      comments?: number
      engagement_score?: number
    }>
    follows?: {
      edges?: number
      top_followees?: Array<{ user_id: number; followers: number }>
    }
    engagement_delta?: number
    previous_engagement_score?: number
  }
}

export type OasisMeasurementRow = {
  tick_key: string
  day: number
  tick_index: number
  kinds: string[]
  points: OasisMeasurementPoint[]
}

export type OasisPlatform = "twitter" | "reddit"

export type OasisRunOptions = {
  platform: OasisPlatform
  allow_population_create_post: boolean
}

export type LexicalConvergenceWarning = {
  phrase: string
  agent_share: number
  agent_count: number
  kind: "source_phrase_echo" | "cross_agent_convergence"
  source?: string
}

export type QualityWarnings = {
  threshold: number
  population_agents: number
  warnings: LexicalConvergenceWarning[]
}

export type OasisVariantResult = {
  id: string
  label: string
  error?: string | null
  ticks_run?: number
  agents?: Array<{
    index: number
    username: string
    member_name: string
    persona_id: string | null
    role?: "population" | "injector"
  }>
  posts?: Array<{
    post_id: number
    user_id: number
    original_post_id?: number | null
    content: string
    quote_content?: string | null
    num_likes: number
    num_dislikes?: number
    num_shares?: number
    created_at?: string | number
    liked_by?: number[]
    disliked_by?: number[]
    shared_by?: Array<{
      user_id: number
      kind: "repost" | "quote"
      share_post_id?: number
    }>
  }>
  comments?: Array<{
    comment_id: number
    post_id: number
    user_id: number
    content: string
    num_likes?: number
    num_dislikes?: number
    liked_by?: number[]
    disliked_by?: number[]
  }>
  follows?: Array<{
    follow_id?: number
    follower_id: number
    followee_id: number
    created_at?: string | number
  }>
  mutes?: Array<{
    mute_id?: number
    muter_id: number
    mutee_id: number
    created_at?: string | number
  }>
  reports?: Array<{
    report_id?: number
    user_id: number
    post_id: number
    report_reason?: string | null
    created_at?: string | number
  }>
  trace?: Array<{
    user_id: number
    created_at?: string | number
    action: string
    info?: string | null
  }>
  action_histogram?: Array<{ action: string; count: number }>
  tick_markers?: Array<{
    tick_index: number
    day: number
    silent: boolean
    key: string
    rounds?: number
    time_start: number
    time_end: number
  }>
  measurements?: OasisMeasurementRow[]
  quality_warnings?: QualityWarnings
  artifact_db?: string
  profile_path?: string
  profile_csv?: string | null
  profile_json?: string | null
  platform?: OasisPlatform
  oasis_options?: OasisRunOptions
}

export type OasisAttemptResult = {
  id: string
  finished_at?: string | null
  seed?: string
  engine?: string
  error?: string | null
  variants: OasisVariantResult[]
}

/** Stored on a run — may be legacy flat shape; normalize with `normalizeRunAttempts`. */
export type OasisRunResults = {
  engine?: string
  seed?: string
  error?: string
  ticks_run?: number
  attempts?: OasisAttemptResult[]
  variants?: OasisVariantResult[]
  agents?: OasisVariantResult["agents"]
  posts?: OasisVariantResult["posts"]
  comments?: OasisVariantResult["comments"]
  artifact_db?: string
}

export type RunSummary = {
  id: number
  name: string
  status: RunStatus
  population: string
  ticks: number
  variants: number
  seed?: string
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
  /** Library Message id; null = scratch text for this run only. */
  message_id: string | null
}

export type TickInterview = {
  key: string
  persona_id: string
  prompt: string
}

export type Tick = {
  key: string
  day: number
  silent: boolean
  injections: Injection[]
  rounds: number
  measurements: string[]
  interviews: TickInterview[]
}

export type BranchMode = "ab" | "stimulus_control"

export const STIMULUS_VARIANT_LABEL = "Med stimulus"
export const CONTROL_VARIANT_LABEL = "Kontroll (ingen injektion)"

export type BranchState = {
  afterIndex: number
  a: Tick[]
  b: Tick[]
  mode?: BranchMode
}

export type Measurement = {
  id: string
  label: string
}
