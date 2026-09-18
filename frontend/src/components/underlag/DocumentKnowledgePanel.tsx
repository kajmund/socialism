import { useCallback, useEffect, useState } from "react"
import { Bookmark, FileQuestion, Lightbulb, MessageSquareText, Pencil, Trash2 } from "lucide-react"
import {
  createDocumentKnowledge,
  deleteDocumentKnowledge,
  getUnderlag,
  listDocumentKnowledge,
  updateDocumentKnowledge,
  type DocumentKnowledgeAnchor,
  type DocumentKnowledgeItem,
  type DocumentKnowledgeKind,
  type DocumentKnowledgeWrite,
  type UnderlagFile,
} from "@/api/underlag"
import { AdminButton } from "@/components/ui/admin-button"
import { Badge } from "@/components/ui/badge"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

export function DocumentKnowledgePanel({
  file,
  selection,
  onClearSelection,
  onFocusAnchor,
  onFileUpdate,
}: {
  file: UnderlagFile
  selection: DocumentKnowledgeAnchor | null
  onClearSelection: () => void
  onFocusAnchor: (anchor: DocumentKnowledgeAnchor) => void
  onFileUpdate: (file: UnderlagFile) => void
}) {
  const { t } = useLocale()
  const [items, setItems] = useState<DocumentKnowledgeItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<DocumentKnowledgeItem | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const rows = await listDocumentKnowledge(file.id)
      setItems(rows)
      setError(null)
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : t("underlag.knowledge.loadError"))
    } finally {
      setLoading(false)
    }
  }, [file.id, t])

  useEffect(() => {
    setItems([])
    setEditing(null)
    setConfirmDeleteId(null)
    setLoading(true)
    void refresh()
  }, [file.id, refresh])

  useEffect(() => {
    if (file.knowledge_status !== "pending" && file.knowledge_status !== "running") return
    let cancelled = false
    const poll = window.setInterval(() => {
      void Promise.all([getUnderlag(file.id), listDocumentKnowledge(file.id)])
        .then(([updated, rows]) => {
          if (cancelled) return
          onFileUpdate(updated)
          setItems(rows)
          setLoading(false)
          setError(null)
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setError(caught instanceof ApiError ? caught.message : t("underlag.knowledge.loadError"))
          }
        })
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(poll)
    }
  }, [file.id, file.knowledge_status, onFileUpdate, t])

  async function remove(itemId: string) {
    try {
      await deleteDocumentKnowledge(file.id, itemId)
      setItems((current) => current.filter((item) => item.id !== itemId))
      setConfirmDeleteId(null)
      if (editing?.id === itemId) setEditing(null)
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : t("underlag.knowledge.deleteError"))
    }
  }

  const formAnchor = editing?.anchors[0] ?? selection

  return (
    <aside className="flex min-h-0 flex-col rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0">
      <div className="shrink-0 border-b border-[color:var(--border-hairline)] px-3 py-3">
        <p className="text-sm font-semibold text-[color:var(--text-body)]">
          {t("underlag.knowledge.title")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("underlag.knowledge.description")}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <KnowledgeStatus file={file} />
        {error ? <p className="mb-3 text-sm text-destructive" role="alert">{error}</p> : null}

        {formAnchor ? (
          <KnowledgeForm
            key={editing?.id ?? `${formAnchor.page_number}:${formAnchor.exact_text}`}
            item={editing}
            anchor={formAnchor}
            onCancel={() => {
              setEditing(null)
              onClearSelection()
            }}
            onSaved={(saved) => {
              setItems((current) => {
                const exists = current.some((item) => item.id === saved.id)
                return exists
                  ? current.map((item) => (item.id === saved.id ? saved : item))
                  : [...current, saved]
              })
              setEditing(null)
              onClearSelection()
            }}
            onError={setError}
            sourceId={file.id}
          />
        ) : file.extraction_status === "ok" ? (
          <p className="mb-3 rounded-md border border-dashed border-[color:var(--border-hairline)] px-3 py-2 text-xs text-muted-foreground">
            {t("underlag.knowledge.selectionHint")}
          </p>
        ) : null}

        {loading ? (
          <p className="text-sm text-muted-foreground">{t("underlag.knowledge.loading")}</p>
        ) : items.length === 0 && file.knowledge_status === "ready" ? (
          <p className="text-sm text-muted-foreground">{t("underlag.knowledge.empty")}</p>
        ) : (
          <div className="space-y-2">
            {items.map((item) => {
              const anchor = item.anchors[0]
              const deleting = confirmDeleteId === item.id
              return (
                <article
                  key={item.id}
                  className={cn(
                    "rounded-md border border-[color:var(--border-hairline)] bg-muted/20 p-3",
                    item.status === "needs_review" && "border-amber-500/50",
                  )}
                >
                  <button
                    type="button"
                    className="block w-full text-left"
                    disabled={!anchor}
                    onClick={() => anchor && onFocusAnchor(anchor)}
                  >
                    <span className="flex items-start gap-2">
                      <KindIcon kind={item.kind} />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium text-[color:var(--text-body)]">
                          {item.question || item.title}
                        </span>
                        {item.content ? (
                          <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                            {item.content}
                          </span>
                        ) : null}
                      </span>
                    </span>
                  </button>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline">{t(kindKey(item.kind))}</Badge>
                    <Badge variant={item.origin === "generated" ? "secondary" : "outline"}>
                      {item.origin === "generated"
                        ? t("underlag.knowledge.generated")
                        : t("underlag.knowledge.manual")}
                    </Badge>
                    {item.revision > 1 ? (
                      <span className="text-[11px] text-muted-foreground">
                        {t("underlag.knowledge.revision", { revision: item.revision })}
                      </span>
                    ) : null}
                    {anchor?.page_number ? (
                      <span className="text-[11px] text-muted-foreground">
                        {t("underlag.knowledge.page", { page: anchor.page_number })}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-2 flex justify-end gap-1">
                    {deleting ? (
                      <>
                        <AdminButton variant="secondary" size="sm" onClick={() => setConfirmDeleteId(null)}>
                          {t("common.cancel")}
                        </AdminButton>
                        <AdminButton variant="primary" size="sm" onClick={() => void remove(item.id)}>
                          {t("common.deleteConfirm")}
                        </AdminButton>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="inline-flex size-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
                          aria-label={t("underlag.knowledge.edit")}
                          title={t("underlag.knowledge.edit")}
                          onClick={() => {
                            setEditing(item)
                            if (anchor) onFocusAnchor(anchor)
                          }}
                        >
                          <Pencil className="size-3.5" aria-hidden />
                        </button>
                        <button
                          type="button"
                          className="inline-flex size-7 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-destructive"
                          aria-label={t("underlag.knowledge.delete")}
                          title={t("underlag.knowledge.delete")}
                          onClick={() => setConfirmDeleteId(item.id)}
                        >
                          <Trash2 className="size-3.5" aria-hidden />
                        </button>
                      </>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </div>
    </aside>
  )
}

function KnowledgeForm({
  item,
  anchor,
  sourceId,
  onCancel,
  onSaved,
  onError,
}: {
  item: DocumentKnowledgeItem | null
  anchor: DocumentKnowledgeAnchor
  sourceId: string
  onCancel: () => void
  onSaved: (item: DocumentKnowledgeItem) => void
  onError: (message: string | null) => void
}) {
  const { t } = useLocale()
  const [kind, setKind] = useState<DocumentKnowledgeKind>(item?.kind ?? "fact")
  const [title, setTitle] = useState(item?.title ?? "")
  const [question, setQuestion] = useState(item?.question ?? "")
  const [content, setContent] = useState(item?.content ?? "")
  const [saving, setSaving] = useState(false)

  async function save() {
    const body: DocumentKnowledgeWrite = {
      kind,
      title: title.trim(),
      question: kind === "qa" ? question.trim() : null,
      content: kind === "bookmark" ? null : content.trim(),
      anchors: item?.anchors ?? [anchor],
    }
    setSaving(true)
    onError(null)
    try {
      const saved = item
        ? await updateDocumentKnowledge(sourceId, item.id, body)
        : await createDocumentKnowledge(sourceId, body)
      onSaved(saved)
    } catch (caught: unknown) {
      onError(caught instanceof ApiError ? caught.message : t("underlag.knowledge.saveError"))
    } finally {
      setSaving(false)
    }
  }

  const valid =
    title.trim().length > 0 &&
    (kind === "bookmark" || content.trim().length > 0) &&
    (kind !== "qa" || question.trim().length > 0)

  return (
    <div className="mb-3 rounded-md border border-db-gold-500/50 bg-db-gold-500/5 p-3">
      <p className="text-xs font-semibold text-[color:var(--text-body)]">
        {item ? t("underlag.knowledge.editTitle") : t("underlag.knowledge.createTitle")}
      </p>
      <p className="mt-1 line-clamp-3 text-xs italic text-muted-foreground">
        “{anchor.exact_text}”
      </p>
      <label className="mt-3 block text-xs text-muted-foreground">
        {t("underlag.knowledge.typeLabel")}
        <select
          value={kind}
          className="mt-1 w-full rounded border border-[color:var(--border-hairline)] bg-db-ink-0 px-2 py-1.5 text-sm text-[color:var(--text-body)]"
          onChange={(event) => setKind(event.target.value as DocumentKnowledgeKind)}
        >
          {(["fact", "qa", "bookmark", "note"] as const).map((value) => (
            <option key={value} value={value}>{t(kindKey(value))}</option>
          ))}
        </select>
      </label>
      <label className="mt-2 block text-xs text-muted-foreground">
        {t("underlag.knowledge.titleLabel")}
        <input
          value={title}
          maxLength={500}
          className="mt-1 w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-[color:var(--text-body)]"
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      {kind === "qa" ? (
        <label className="mt-2 block text-xs text-muted-foreground">
          {t("underlag.knowledge.questionLabel")}
          <textarea
            value={question}
            rows={2}
            maxLength={4000}
            className="mt-1 w-full resize-y rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-[color:var(--text-body)]"
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>
      ) : null}
      {kind !== "bookmark" ? (
        <label className="mt-2 block text-xs text-muted-foreground">
          {kind === "qa" ? t("underlag.knowledge.answerLabel") : t("underlag.knowledge.contentLabel")}
          <textarea
            value={content}
            rows={3}
            maxLength={12000}
            className="mt-1 w-full resize-y rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-[color:var(--text-body)]"
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
      ) : null}
      <div className="mt-3 flex justify-end gap-2">
        <AdminButton variant="secondary" size="sm" disabled={saving} onClick={onCancel}>
          {t("common.cancel")}
        </AdminButton>
        <AdminButton variant="primary" size="sm" disabled={!valid || saving} onClick={() => void save()}>
          {saving ? t("underlag.knowledge.saving") : t("common.save")}
        </AdminButton>
      </div>
    </div>
  )
}

function KnowledgeStatus({ file }: { file: UnderlagFile }) {
  const { t } = useLocale()
  switch (file.knowledge_status) {
    case "pending":
    case "running":
      return <p className="mb-3 text-xs text-muted-foreground">{t("underlag.knowledge.processing")}</p>
    case "needs_ocr":
      return <p className="mb-3 text-xs text-amber-600">{t("underlag.knowledge.needsOcr")}</p>
    case "empty":
      return <p className="mb-3 text-xs text-muted-foreground">{t("underlag.knowledge.noText")}</p>
    case "failed":
      return (
        <p className="mb-3 text-xs text-destructive">
          {file.knowledge_error || t("underlag.knowledge.failed")}
        </p>
      )
    default:
      return null
  }
}

function KindIcon({ kind }: { kind: DocumentKnowledgeKind }) {
  const className = "mt-0.5 size-4 shrink-0 text-db-gold-600"
  switch (kind) {
    case "fact":
      return <Lightbulb className={className} aria-hidden />
    case "qa":
      return <FileQuestion className={className} aria-hidden />
    case "bookmark":
      return <Bookmark className={className} aria-hidden />
    case "note":
      return <MessageSquareText className={className} aria-hidden />
  }
}

function kindKey(kind: DocumentKnowledgeKind): MessageKey {
  switch (kind) {
    case "fact":
      return "underlag.knowledge.kind.fact"
    case "qa":
      return "underlag.knowledge.kind.qa"
    case "bookmark":
      return "underlag.knowledge.kind.bookmark"
    case "note":
      return "underlag.knowledge.kind.note"
  }
}
