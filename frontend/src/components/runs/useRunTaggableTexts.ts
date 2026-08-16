import { useCallback, useEffect, useState } from "react"
import {
  fetchRunTaggableTexts,
  type RunTaggableTextRow,
  type RunTaggableTextsResponse,
} from "@/api/runs"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function sourceRefKey(ref: Record<string, unknown>): string {
  return JSON.stringify(ref, Object.keys(ref).sort())
}

export function useRunTaggableTexts(
  runId?: number,
  attemptId?: string,
  variantId?: string,
) {
  const { locale, t } = useLocale()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<RunTaggableTextsResponse | null>(null)

  const reload = useCallback(async () => {
    if (runId == null || !attemptId || !variantId) {
      setData(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const next = await fetchRunTaggableTexts(runId, {
        attemptId,
        variantId,
        locale,
      })
      setData(next)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("runs.results.anchorPool.loadError"),
      )
    } finally {
      setLoading(false)
    }
  }, [attemptId, locale, runId, t, variantId])

  useEffect(() => {
    void reload()
  }, [reload])

  const rows = data?.rows ?? []
  const byCommentId = new Map<number, RunTaggableTextRow>()
  for (const row of rows) {
    if (row.source_type !== "comment") continue
    const commentId = row.source_ref.comment_id
    if (typeof commentId === "number") {
      byCommentId.set(commentId, row)
    }
  }

  return {
    loading,
    error,
    data,
    rows,
    byCommentId,
    context: data?.anchor_context ?? null,
    reload,
  }
}
