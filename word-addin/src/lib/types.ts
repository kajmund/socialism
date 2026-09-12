export type WordParagraph = {
  index: number
  text: string
  style: string
  list_string: string
  unique_local_id?: string | null
}

export type WordTaskType = "review"
export type WordTaskScopeType = "document" | "selection"

export type WordTaskScope =
  | { type: "document" }
  | { type: "selection"; paragraph_indexes: number[] }

export type WordExpertStrategy = {
  type: "panel"
  panel_id: number
}

export type WordTask = {
  task_type: WordTaskType
  scope: WordTaskScope
  expert_strategy: WordExpertStrategy
}

export const INTENT_QUESTION_TYPES = [
  "single_choice",
  "multi_choice",
  "free_text",
] as const
export type IntentQuestionType = (typeof INTENT_QUESTION_TYPES)[number]

export type IntentOption = {
  value: string
  label: string
}

export type IntentQuestion = {
  id: string
  text: string
  type: IntentQuestionType
  options: IntentOption[]
  required: boolean
  rationale: string
}

export type DocumentIntentInterview = {
  document_type: string
  questions: IntentQuestion[]
}

export type IntentAnswer = {
  question_id: string
  selected_values: string[]
  free_text: string | null
}

export type WordDocumentSection = {
  heading: string
  heading_style: string
  heading_paragraph_index: number
  heading_unique_local_id?: string | null
  paragraphs: WordParagraph[]
}

export type WordAnchor = {
  paragraph_index: number
  unique_local_id?: string | null
  reviewed_text: string
  text_hash: string
  previous_text_hash?: string | null
  next_text_hash?: string | null
  word_session_id?: string | null
}

export type ExpertPanelSummary = {
  id: number
  name: string
  kind: string
}

export type WordActionSource = {
  type: string
  id: string
  ordinal: number
}

export type WordAction = {
  id: string
  job_id: string
  action_type: string
  anchor?: WordAnchor | null
  content: string
  explanation?: string | null
  status: string
  application_id?: string | null
  application_error?: string | null
  word_artifact_id?: string | null
  source?: WordActionSource
  created_at?: string
}

export type LatestWordJob = {
  job_id: string
  status: string
  error?: string | null
  actions: WordAction[]
}

export type WatchReplay = {
  type: "expertgranskning.replay"
  job_id: string
  status: string
  actions: WordAction[]
}

export type WatchCreated = {
  type: "expertgranskning.action.created"
  job_id: string
  action: WordAction
}

export type WatchUpdated = {
  type: "expertgranskning.action.updated"
  job_id: string
  action: WordAction
}

export type WatchFinished = {
  type: "expertgranskning.finished"
  job_id: string
  status: string
  error?: string
}

export type WatchProgress = {
  type: "expertgranskning.progress"
  job_id: string
  sections_completed: number
  sections_total: number
  actions_created: number
}

export type WatchEvent =
  | WatchReplay
  | WatchCreated
  | WatchUpdated
  | WatchProgress
  | WatchFinished
