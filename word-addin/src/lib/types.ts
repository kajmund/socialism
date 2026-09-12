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

export type ReviewResult = {
  id: string
  job_id: string
  paragraph_index: number
  expert_id: string
  expert_namn: string
  kommentar: string
  is_heading_suggestion: boolean
  is_rewrite_suggestion?: boolean
  foreslagen_text?: string | null
  reviewed_text?: string | null
  anchor?: WordAnchor | null
  comment_id: string | null
  application_id?: string | null
  application_error?: string | null
  status: string
}

export type LatestWordJob = {
  job_id: string
  status: string
  results: ReviewResult[]
}

export type WatchReplay = {
  type: "expertgranskning.replay"
  job_id: string
  status: string
  results: ReviewResult[]
}

export type WatchCreated = {
  type: "expertgranskning.result.created"
  job_id: string
  result: ReviewResult
}

export type WatchUpdated = {
  type: "expertgranskning.result.updated"
  job_id: string
  result: ReviewResult
}

export type WatchFinished = {
  type: "expertgranskning.finished"
  job_id: string
  status: string
  error?: string
}

export type WatchEvent = WatchReplay | WatchCreated | WatchUpdated | WatchFinished
