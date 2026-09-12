import { env } from "@/lib/env"
import { ApiError, httpRequest } from "@/lib/http"
import type {
  DocumentIntentInterview,
  ExpertPanelSummary,
  IntentAnswer,
  LatestWordJob,
  WordAction,
  WordDocumentSection,
  WordTask,
} from "@/lib/types"
import { InvalidIntentInterviewError, parseIntentInterview } from "@/lib/intentInterview"

function url(path: string): string {
  return `${env.apiBaseUrl.replace(/\/$/, "")}${path}`
}

export async function listExpertPanels(token: string): Promise<ExpertPanelSummary[]> {
  const rows = await httpRequest<ExpertPanelSummary[]>(
    url("/populations?kind=expert_panel"),
    { token },
  )
  return rows.filter((row) => row.kind === "expert_panel")
}

export function isIntentInterviewInvalidError(error: unknown): boolean {
  return (
    error instanceof InvalidIntentInterviewError ||
    (error instanceof ApiError && error.message === "intent_interview_invalid")
  )
}

export async function generateIntentInterview(
  token: string,
  body: {
    panel_id: number
    sections: WordDocumentSection[]
    locale?: "sv" | "en" | "nb"
  },
): Promise<DocumentIntentInterview> {
  try {
    const created = await httpRequest<unknown>(
      url("/expertgranskning/word-intent-interview"),
      {
        method: "POST",
        token,
        body,
      },
    )
    return parseIntentInterview(created)
  } catch (error) {
    if (isIntentInterviewInvalidError(error)) {
      throw new InvalidIntentInterviewError()
    }
    throw error
  }
}

export async function createWordJob(
  token: string,
  body: {
    task: WordTask
    doc_id: string
    sections: WordDocumentSection[]
    locale?: "sv" | "en" | "nb"
    word_session_id?: string
    review_intent?: string
    intent_interview?: DocumentIntentInterview
    intent_answers?: IntentAnswer[]
  },
): Promise<string> {
  const created = await httpRequest<{ job_id: string }>(url("/expertgranskning/word-jobs"), {
    method: "POST",
    token,
    body,
  })
  return created.job_id
}

export async function getLatestWordJob(
  token: string,
  docId: string,
): Promise<LatestWordJob | null> {
  try {
    return await httpRequest<LatestWordJob>(
      url(`/expertgranskning/word-jobs/latest?doc_id=${encodeURIComponent(docId)}`),
      { token },
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null
    }
    throw error
  }
}

export async function claimAction(
  token: string,
  jobId: string,
  actionId: string,
  applicationId: string,
): Promise<{ claimed: boolean; action?: WordAction }> {
  try {
    const action = await httpRequest<WordAction>(
      url(`/expertgranskning/word-jobs/${jobId}/actions/${actionId}/claim`),
      {
        method: "POST",
        token,
        body: { application_id: applicationId },
      },
    )
    return { claimed: true, action }
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      return { claimed: false }
    }
    throw error
  }
}

export async function completeAction(
  token: string,
  jobId: string,
  actionId: string,
  applicationId: string,
  wordArtifactId: string,
): Promise<WordAction> {
  return httpRequest<WordAction>(
    url(`/expertgranskning/word-jobs/${jobId}/actions/${actionId}/complete`),
    {
      method: "POST",
      token,
      body: { application_id: applicationId, word_artifact_id: wordArtifactId },
    },
  )
}

export async function markActionUnresolved(
  token: string,
  jobId: string,
  actionId: string,
  reason: string,
  applicationId?: string,
): Promise<WordAction> {
  return httpRequest<WordAction>(
    url(`/expertgranskning/word-jobs/${jobId}/actions/${actionId}/unresolved`),
    {
      method: "POST",
      token,
      body: {
        reason,
        ...(applicationId ? { application_id: applicationId } : {}),
      },
    },
  )
}

export async function dismissAction(
  token: string,
  jobId: string,
  actionId: string,
): Promise<WordAction> {
  return httpRequest<WordAction>(
    url(`/expertgranskning/word-jobs/${jobId}/actions/${actionId}/dismiss`),
    {
      method: "POST",
      token,
    },
  )
}

export async function listWordActions(
  token: string,
  jobId: string,
): Promise<WordAction[]> {
  return httpRequest<WordAction[]>(
    url(`/expertgranskning/word-jobs/${jobId}/actions`),
    { token },
  )
}
