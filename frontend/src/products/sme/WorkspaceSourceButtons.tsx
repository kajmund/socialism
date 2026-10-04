import { useState } from "react"
import { RotateCcw } from "lucide-react"
import type { UnderlagFile } from "@/api/underlag"
import { useLocale } from "@/i18n"

export function WorkspaceSourceButtons({ sources, sourceStatus, onOpen, onRetry, onError }: {
  sources: UnderlagFile[]
  sourceStatus: (status: string | null | undefined) => string
  onOpen: (sourceId: string) => void
  onRetry: (sourceId: string) => Promise<unknown>
  onError: (error: unknown) => void
}) {
  const { t } = useLocale()
  const [retrying, setRetrying] = useState<string[]>([])
  const retry = async (sourceId: string) => {
    setRetrying((current) => [...current, sourceId])
    try { await onRetry(sourceId) } catch (error) { onError(error) }
    finally { setRetrying((current) => current.filter((id) => id !== sourceId)) }
  }
  return sources.map((source) => <span key={source.id} className="flex shrink-0 items-center rounded-lg border text-xs">
    <button type="button" className="flex items-center gap-2 px-3 py-1.5" title={source.knowledge_error ?? sourceStatus(source.knowledge_status)} onClick={() => onOpen(source.id)}>
      <span className="max-w-40 truncate">{source.filename}</span><span className={source.knowledge_status === "failed" || source.knowledge_status === "needs_ocr" ? "text-destructive" : "text-muted-foreground"}>{sourceStatus(source.knowledge_status)}</span>
    </button>
    {source.knowledge_status === "failed" ? <button type="button" className="flex items-center gap-1 border-l px-2 py-1.5 disabled:opacity-50" aria-label={t("voiceWorkspaceChat.retrySource", { name: source.filename })} disabled={retrying.includes(source.id)} onClick={() => { void retry(source.id) }}><RotateCcw size={13} />{t("voiceWorkspaceChat.retry")}</button> : null}
  </span>)
}
