import { useEffect, useRef, useState, type FormEvent } from "react"

import { useLocale } from "@/i18n/LocaleContext"
import {
  createWordJob,
  getLatestWordJob,
  listExpertPanels,
  patchResultCommentId,
} from "@/lib/api"
import {
  commentsApiSupported,
  getOrCreateDocId,
  getRoamingToken,
  insertCommentAt,
  officeReady,
  readDocumentParagraphs,
  resolveComment,
  saveRoamingToken,
} from "@/lib/office"
import { buildSections } from "@/lib/sections"
import { connectExpertgranskningWatch } from "@/lib/socket"
import type { ExpertPanelSummary, ReviewResult } from "@/lib/types"
import { actionsForWatchEvent, formatCommentBody, isWatchEvent } from "@/lib/watch"

type Phase = "idle" | "running" | "done" | "failed"

export function App() {
  const { t, locale, setLocale } = useLocale()
  const [token, setToken] = useState("")
  const [tokenDraft, setTokenDraft] = useState("")
  const [panels, setPanels] = useState<ExpertPanelSummary[]>([])
  const [panelId, setPanelId] = useState("")
  const [phase, setPhase] = useState<Phase>("idle")
  const [error, setError] = useState("")
  const [insertedCount, setInsertedCount] = useState(0)
  const [inWord, setInWord] = useState(false)
  const insertedIds = useRef(new Set<string>())
  const socketRef = useRef<{ close: () => void } | null>(null)
  const applyQueue = useRef(Promise.resolve())

  useEffect(() => {
    void officeReady().then(() => {
      setInWord(typeof Office !== "undefined" && Office.context?.document != null)
      const stored = getRoamingToken().trim()
      if (stored) {
        setToken(stored)
        setTokenDraft(stored)
      }
    })
    return () => {
      socketRef.current?.close()
    }
  }, [])

  useEffect(() => {
    if (!token) {
      setPanels([])
      return
    }
    let cancelled = false
    void listExpertPanels(token)
      .then((rows) => {
        if (cancelled) return
        setPanels(rows)
        setPanelId((current) => {
          if (current && rows.some((row) => String(row.id) === current)) {
            return current
          }
          return rows[0] ? String(rows[0].id) : ""
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [token])

  async function handleSaveToken(event: FormEvent) {
    event.preventDefault()
    const next = tokenDraft.trim()
    if (!next) return
    if (typeof Office !== "undefined") {
      await saveRoamingToken(next)
    }
    setToken(next)
    setError("")
  }

  async function insertOne(jobId: string, result: ReviewResult) {
    insertedIds.current.add(result.id)
    const commentId = await insertCommentAt(
      result.paragraph_index,
      formatCommentBody(result),
    )
    await patchResultCommentId(token, jobId, result.id, commentId)
    setInsertedCount((count) => count + 1)
  }

  async function applyWatchPayload(jobId: string, data: unknown) {
    if (!isWatchEvent(data) || data.job_id !== jobId) return
    const actions = actionsForWatchEvent(data, insertedIds.current)
    for (const action of actions) {
      switch (action.kind) {
        case "remember":
          for (const id of action.ids) insertedIds.current.add(id)
          break
        case "insert":
          for (const result of action.results) {
            try {
              await insertOne(jobId, result)
            } catch (err) {
              insertedIds.current.delete(result.id)
              throw err
            }
          }
          break
        case "finished":
          if (action.status === "failed") {
            setPhase("failed")
            setError(action.error || action.status)
          } else {
            setPhase("done")
          }
          socketRef.current?.close()
          socketRef.current = null
          break
        default: {
          const _exhaustive: never = action
          return _exhaustive
        }
      }
    }
  }

  async function handleReview() {
    setError("")
    if (!inWord) {
      setError(t("officeMissing"))
      return
    }
    if (!commentsApiSupported()) {
      setError(t("commentsUnsupported"))
      return
    }
    if (!token || !panelId) return

    socketRef.current?.close()
    socketRef.current = null
    insertedIds.current = new Set()
    setInsertedCount(0)
    setPhase("running")

    try {
      const docId = await getOrCreateDocId()
      const previous = await getLatestWordJob(token, docId)
      if (previous) {
        for (const row of previous.results) {
          if (!row.comment_id) continue
          try {
            await resolveComment(row.comment_id)
          } catch {
            // Already resolved or missing in this document.
          }
        }
      }

      const paragraphs = await readDocumentParagraphs()
      if (paragraphs.length === 0) {
        setPhase("idle")
        setError(t("noParagraphs"))
        return
      }
      const sections = buildSections(paragraphs)
      if (sections.length === 0) {
        setPhase("idle")
        setError(t("noSections"))
        return
      }

      const jobId = await createWordJob(token, {
        panel_id: Number(panelId),
        doc_id: docId,
        sections,
        locale: locale === "en" ? "en" : "sv",
      })

      socketRef.current = connectExpertgranskningWatch({
        token,
        jobId,
        onMessage(data) {
          applyQueue.current = applyQueue.current
            .then(() => applyWatchPayload(jobId, data))
            .catch((err: unknown) => {
              setPhase("failed")
              setError(err instanceof Error ? err.message : String(err))
            })
        },
      })
    } catch (err) {
      setPhase("failed")
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const canReview = Boolean(token && panelId) && phase !== "running"

  return (
    <div className="pane">
      <header className="pane-head">
        <h1>{t("title")}</h1>
        <label className="lang">
          <span>{t("language")}</span>
          <select
            value={locale}
            onChange={(event) => setLocale(event.target.value === "en" ? "en" : "sv")}
          >
            <option value="sv">Svenska</option>
            <option value="en">English</option>
          </select>
        </label>
      </header>

      <form className="block" onSubmit={(event) => void handleSaveToken(event)}>
        <label htmlFor="token">{t("tokenLabel")}</label>
        <textarea
          id="token"
          rows={3}
          value={tokenDraft}
          onChange={(event) => setTokenDraft(event.target.value)}
        />
        <p className="hint">{t("tokenHint")}</p>
        <button type="submit">{t("tokenSave")}</button>
        {token ? <p className="ok">{t("tokenSaved")}</p> : null}
      </form>

      <div className="block">
        <label htmlFor="panel">{t("panelLabel")}</label>
        <select
          id="panel"
          value={panelId}
          onChange={(event) => setPanelId(event.target.value)}
          disabled={!token || panels.length === 0}
        >
          {panels.length === 0 ? (
            <option value="">{t("panelPlaceholder")}</option>
          ) : null}
          {panels.map((panel) => (
            <option key={panel.id} value={panel.id}>
              {panel.name}
            </option>
          ))}
        </select>
        {token && panels.length === 0 ? <p className="hint">{t("panelEmpty")}</p> : null}
      </div>

      <button
        type="button"
        className="primary"
        disabled={!canReview}
        onClick={() => void handleReview()}
      >
        {phase === "running" ? t("reviewing") : t("review")}
      </button>

      <p className="status" data-phase={phase}>
        {phase === "idle" ? t("statusIdle") : null}
        {phase === "running" ? t("statusLive") : null}
        {phase === "done" ? t("statusDone") : null}
        {phase === "failed" ? t("statusFailed", { error }) : null}
      </p>
      {phase !== "failed" && error ? <p className="error">{error}</p> : null}
      {insertedCount > 0 ? <p className="hint">{t("inserted", { count: insertedCount })}</p> : null}
    </div>
  )
}
