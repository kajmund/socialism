import { useCallback, useEffect, useRef, useState } from "react"
import {
  createClassification,
  fetchQueue,
  listClassifications,
  recordDecision,
  undoDecision,
  type ClauseClassification,
  type DecisionAnswer,
  type QueueCard,
  type QueuePage,
} from "@/api/clauseSsr"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { isTypingTarget, keyToQueueAction } from "@/pages/clauseSsrKeys"

const PREFETCH = 5

export function ClauseSsrQueuePage() {
  const { t, intl } = useLocale()
  const [classifications, setClassifications] = useState<ClauseClassification[]>([])
  const [classificationId, setClassificationId] = useState("")
  const [documentId, setDocumentId] = useState("")
  const [page, setPage] = useState<QueuePage | null>(null)
  const [history, setHistory] = useState<QueueCard[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newQuestion, setNewQuestion] = useState("")
  const [newSlug, setNewSlug] = useState("")
  const [newCategory, setNewCategory] = useState("")
  const inflight = useRef(false)

  const loadClassifications = useCallback(async () => {
    const data = await listClassifications()
    setClassifications(data.items)
    setClassificationId((current) => current || data.items[0]?.id || "")
  }, [])

  const loadQueue = useCallback(async (id: string, doc: string) => {
    if (!id) {
      setPage(null)
      return
    }
    const next = await fetchQueue({
      classificationId: id,
      documentId: doc || undefined,
      limit: PREFETCH,
    })
    setPage(next)
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    void loadClassifications()
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("clauseSsr.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadClassifications, t])

  useEffect(() => {
    if (!classificationId) return
    let cancelled = false
    void loadQueue(classificationId, documentId).catch((err: unknown) => {
      if (!cancelled) {
        setError(err instanceof ApiError ? err.message : t("clauseSsr.loadError"))
      }
    })
    return () => {
      cancelled = true
    }
  }, [classificationId, documentId, loadQueue, t])

  const card = page?.cards[0] ?? null

  const decide = useCallback(
    async (answer: DecisionAnswer) => {
      if (!card || !classificationId || inflight.current) return
      inflight.current = true
      setBusy(true)
      setError(null)
      try {
        await recordDecision({
          classification_id: classificationId,
          unit_id: card.unit_id,
          answer,
          document_id: documentId || undefined,
        })
        setHistory((prev) => [...prev, card])
        const remaining = page?.cards.slice(1) ?? []
        if (remaining.length >= 2) {
          setPage((current) =>
            current
              ? {
                  ...current,
                  cards: remaining,
                  remaining: Math.max(0, current.remaining - 1),
                }
              : current,
          )
          void loadQueue(classificationId, documentId).catch(() => undefined)
        } else {
          await loadQueue(classificationId, documentId)
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : t("clauseSsr.saveError"))
      } finally {
        inflight.current = false
        setBusy(false)
      }
    },
    [card, classificationId, documentId, loadQueue, page, t],
  )

  const onUndo = useCallback(async () => {
    if (!classificationId || inflight.current) return
    inflight.current = true
    setBusy(true)
    setError(null)
    try {
      await undoDecision({
        classification_id: classificationId,
        document_id: documentId || undefined,
      })
      setHistory((prev) => prev.slice(0, -1))
      await loadQueue(classificationId, documentId)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("clauseSsr.saveError"))
    } finally {
      inflight.current = false
      setBusy(false)
    }
  }, [classificationId, documentId, loadQueue, t])

  const onPrev = useCallback(() => {
    const previous = history.at(-1)
    if (!previous || !page) return
    setPage({ ...page, cards: [previous, ...page.cards] })
    setHistory((prev) => prev.slice(0, -1))
  }, [history, page])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (isTypingTarget(event.target) || busy) return
      const action = keyToQueueAction(event.key)
      if (action == null) return
      event.preventDefault()
      if (action === "undo") {
        void onUndo()
        return
      }
      if (action === "prev") {
        onPrev()
        return
      }
      void decide(action)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [busy, decide, onPrev, onUndo])

  async function onCreateClassification() {
    if (!newQuestion.trim() || !newSlug.trim() || !newCategory.trim()) return
    setBusy(true)
    setError(null)
    try {
      const created = await createClassification({
        slug: newSlug.trim(),
        question: newQuestion.trim(),
        category: newCategory.trim(),
      })
      setNewQuestion("")
      setNewSlug("")
      setNewCategory("")
      await loadClassifications()
      setClassificationId(created.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("clauseSsr.saveError"))
    } finally {
      setBusy(false)
    }
  }

  const similarityLabel =
    card?.similarity == null
      ? null
      : new Intl.NumberFormat(intl, { maximumFractionDigits: 3 }).format(card.similarity)

  return (
    <div className="space-y-4">
      <div className="space-y-4">
        <div>
          <p className="kicker">{t("clauseSsr.kicker")}</p>
          <h2>{t("clauseSsr.title")}</h2>
          <p className="muted">{t("clauseSsr.intro")}</p>
        </div>
        <div className="controls-row flex flex-wrap gap-3">
          <label className="grid gap-1 text-sm">
            <span>{t("clauseSsr.classification")}</span>
            <select
              className="dsel"
              value={classificationId}
              onChange={(event) => setClassificationId(event.target.value)}
            >
              {classifications.length === 0 ? (
                <option value="">{t("clauseSsr.noClassifications")}</option>
              ) : null}
              {classifications.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.question}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span>{t("clauseSsr.documentFilter")}</span>
            <input
              className="dsearch"
              value={documentId}
              onChange={(event) => setDocumentId(event.target.value)}
              placeholder={t("clauseSsr.documentPlaceholder")}
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            className="dsearch"
            value={newSlug}
            onChange={(event) => setNewSlug(event.target.value)}
            placeholder={t("clauseSsr.newSlug")}
          />
          <input
            className="dsearch"
            value={newCategory}
            onChange={(event) => setNewCategory(event.target.value)}
            placeholder={t("clauseSsr.newCategory")}
          />
          <input
            className="dsearch min-w-64"
            value={newQuestion}
            onChange={(event) => setNewQuestion(event.target.value)}
            placeholder={t("clauseSsr.newQuestion")}
          />
          <AdminButton variant="secondary" disabled={busy} onClick={() => void onCreateClassification()}>
            {t("clauseSsr.createQuestion")}
          </AdminButton>
        </div>
        {page ? (
          <p className="muted">
            {t("clauseSsr.progress", {
              answered: page.session.answered,
              remaining: page.remaining,
              skipped: page.session.skipped,
              unsure: page.session.unsure,
            })}
          </p>
        ) : null}
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
      </div>
      <div>
        {loading ? <p className="muted">{t("clauseSsr.loading")}</p> : null}
        {!loading && card == null ? <p className="no-match">{t("clauseSsr.empty")}</p> : null}
        {card ? (
          <Card className="max-w-3xl">
            <CardContent className="space-y-5 p-6">
              <p className="text-xl font-medium">{card.classification.question}</p>
              <p className="whitespace-pre-wrap text-[color:var(--text-body)]">{card.text}</p>
              <dl className="grid gap-1 text-sm text-muted-foreground">
                <div>
                  <dt className="inline">{t("clauseSsr.category")}: </dt>
                  <dd className="inline">{card.classification.category}</dd>
                </div>
                <div>
                  <dt className="inline">{t("clauseSsr.source")}: </dt>
                  <dd className="inline">
                    {card.document_id}
                    {card.locator ? ` · ${card.locator}` : ` · #${card.ordinal + 1}`}
                  </dd>
                </div>
                {similarityLabel ? (
                  <div>
                    <dt className="inline">{t("clauseSsr.similarity")}: </dt>
                    <dd className="inline">
                      {similarityLabel} {t("clauseSsr.similarityHint")}
                    </dd>
                  </div>
                ) : null}
              </dl>
              <div className="flex flex-wrap gap-3">
                <AdminButton
                  className="min-w-28 px-8 py-4 text-lg"
                  disabled={busy}
                  onClick={() => void decide("yes")}
                >
                  {t("clauseSsr.yes")}
                </AdminButton>
                <AdminButton
                  variant="accent"
                  className="min-w-28 px-8 py-4 text-lg"
                  disabled={busy}
                  onClick={() => void decide("no")}
                >
                  {t("clauseSsr.no")}
                </AdminButton>
              </div>
              <div className="flex flex-wrap gap-2">
                <AdminButton variant="secondary" disabled={busy} onClick={() => void decide("skip")}>
                  {t("clauseSsr.skip")}
                </AdminButton>
                <AdminButton variant="secondary" disabled={busy} onClick={() => void decide("unsure")}>
                  {t("clauseSsr.unsure")}
                </AdminButton>
                <AdminButton variant="secondary" disabled={busy || history.length === 0} onClick={onPrev}>
                  {t("clauseSsr.prev")}
                </AdminButton>
                <AdminButton
                  variant="secondary"
                  disabled={busy || !page?.session.last_verification_id}
                  onClick={() => void onUndo()}
                >
                  {t("clauseSsr.undo")}
                </AdminButton>
              </div>
              <p className="muted text-xs">{t("clauseSsr.shortcuts")}</p>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  )
}
