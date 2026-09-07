import { env } from "@/lib/env"
import { ApiError, httpRequest } from "@/lib/http"
import type {
  ExpertPanelSummary,
  LatestWordJob,
  ReviewResult,
  WordDocumentSection,
} from "@/lib/types"

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

export async function createWordJob(
  token: string,
  body: {
    panel_id: number
    doc_id: string
    sections: WordDocumentSection[]
    locale?: "sv" | "en" | "nb"
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

export async function patchResultCommentId(
  token: string,
  jobId: string,
  resultId: string,
  commentId: string,
): Promise<ReviewResult> {
  return httpRequest<ReviewResult>(
    url(`/expertgranskning/word-jobs/${jobId}/results/${resultId}`),
    {
      method: "PATCH",
      token,
      body: { comment_id: commentId },
    },
  )
}
