export type WordParagraph = {
  index: number
  text: string
  style: string
  list_string: string
  unique_local_id?: string | null
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

export type WatchEvent = WatchReplay | WatchCreated | WatchUpdated | WatchFinished
