import { useEffect, useRef, useState, type FormEvent } from "react"

import headMark from "@/assets/devbrains-head.png"
import { useLocale } from "@/i18n/LocaleContext"
import {
  claimResult,
  completeResult,
  createWordJob,
  getLatestWordJob,
  listExpertPanels,
  markResultUnresolved,
} from "@/lib/api"
import { ApiError } from "@/lib/http"
import {
  applyRewriteSuggestion,
  commentsApiSupported,
  getOrCreateDocId,
  getStoredDocId,
  insertCommentForAnchor,
  officeReady,
  paragraphStatesFromSnapshot,
  readDocumentParagraphs,
  resolveComment,
  WORD_SESSION_ID,
} from "@/lib/office"
import { resolveWordAnchor } from "@/lib/word/anchors"
import { clearStoredToken, getStoredToken, saveStoredToken } from "@/lib/tokenStorage"
import { finishedJobView, planReviewStart } from "@/lib/resume"
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
  const [watchSource, setWatchSource] = useState<"new" | "resume">("new")
  const [error, setError] = useState("")
  const [appliedCount, setAppliedCount] = useState(0)
  const [unplacedCount, setUnplacedCount] = useState(0)
  const [inWord, setInWord] = useState(false)
  const insertedIds = useRef(new Set<string>())
  const resultStatus = useRef(new Map<string, string>())
  const socketRef = useRef<{ close: () => void } | null>(null)
  const watchJobId = useRef<string | null>(null)
  const applyQueue = useRef(Promise.resolve())

  function syncApplicationCounts() {
    let applied = 0
    let unplaced = 0
    for (const status of resultStatus.current.values()) {
      if (status === "applied") applied += 1
      if (status === "unresolved" || status === "applying") unplaced += 1
    }
    setAppliedCount(applied)
    setUnplacedCount(unplaced)
  }

  function noteResultStatus(id: string, status: string) {
    resultStatus.current.set(id, status)
    syncApplicationCounts()
  }

  function noteResults(results: ReviewResult[]) {
    for (const row of results) {
      resultStatus.current.set(row.id, row.status)
    }
    syncApplicationCounts()
  }

  function attachWatch(jobId: string, source: "new" | "resume") {
    if (watchJobId.current === jobId && socketRef.current) {
      setPhase("running")
      setWatchSource(source)
      return
    }
    socketRef.current?.close()
    socketRef.current = null
    watchJobId.current = jobId
    insertedIds.current = new Set()
    resultStatus.current = new Map()
    setAppliedCount(0)
    setUnplacedCount(0)
    setWatchSource(source)
    setPhase("running")
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
  }

  useEffect(() => {
    const stored = getStoredToken().trim()
    if (stored) {
      setToken(stored)
      setTokenDraft(stored)
    }
    void officeReady().then(() => {
      setInWord(typeof Office !== "undefined" && Office.context?.document != null)
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

  useEffect(() => {
    if (!token || !inWord || !commentsApiSupported()) return
    const docId = getStoredDocId().trim()
    if (!docId) return
    let cancelled = false
    void getLatestWordJob(token, docId)
      .then((latest) => {
        if (cancelled) return
        const plan = planReviewStart(latest)
        if (plan.action === "resume") {
          attachWatch(plan.jobId, "resume")
          return
        }
        const finished = finishedJobView(latest)
        if (!finished) return
        noteResults(finished.results)
        setPhase(finished.phase)
        if (finished.phase === "failed") {
          setError(finished.phase)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [token, inWord])

  async function handleSaveToken(event: FormEvent) {
    event.preventDefault()
    const next = tokenDraft.trim()
    if (!next) {
      setError(t("tokenEmpty"))
      return
    }
    setToken(next)
    setError("")
    try {
      saveStoredToken(next)
    } catch {
      setError(t("tokenPersistFailed"))
    }
  }

  function handleChangeToken() {
    clearStoredToken()
    setToken("")
    setTokenDraft("")
    setPanels([])
    setPanelId("")
    setError("")
  }

  async function insertOne(jobId: string, result: ReviewResult) {
    insertedIds.current.add(result.id)
    const anchor = result.anchor
    if (!anchor) {
      const marked = await markResultUnresolved(token, jobId, result.id, "missing")
      noteResultStatus(result.id, marked.status)
      return
    }

    const current = paragraphStatesFromSnapshot(await readDocumentParagraphs())
    const resolution = resolveWordAnchor(anchor, current, WORD_SESSION_ID)
    if (resolution.status !== "resolved") {
      const marked = await markResultUnresolved(token, jobId, result.id, resolution.status)
      noteResultStatus(result.id, marked.status)
      return
    }

    const applicationId = crypto.randomUUID()
    const claimed = await claimResult(token, jobId, result.id, applicationId)
    if (!claimed.claimed) {
      if (claimed.result) noteResultStatus(result.id, claimed.result.status)
      return
    }
    noteResultStatus(result.id, "applying")

    try {
      const outcome = result.is_rewrite_suggestion
        ? await applyRewriteSuggestion({
            anchor,
            foreslagenText: (result.foreslagen_text ?? "").trim(),
            motivering: formatCommentBody(result) || t("rewritePrefix"),
            fallbackComment: `${t("rewritePrefix")} ${(result.foreslagen_text ?? "").trim()}`.trim(),
          })
        : await insertCommentForAnchor(anchor, formatCommentBody(result))
      if (outcome.status !== "resolved") {
        const marked = await markResultUnresolved(
          token,
          jobId,
          result.id,
          outcome.status,
          applicationId,
        )
        noteResultStatus(result.id, marked.status)
        return
      }
      const completed = await completeResult(
        token,
        jobId,
        result.id,
        applicationId,
        outcome.commentId,
      )
      noteResultStatus(result.id, completed.status)
    } catch {
      noteResultStatus(result.id, "applying")
    }
  }

  async function applyWatchPayload(jobId: string, data: unknown) {
    if (!isWatchEvent(data) || data.job_id !== jobId) return
    switch (data.type) {
      case "expertgranskning.replay":
        noteResults(data.results)
        break
      case "expertgranskning.result.created":
      case "expertgranskning.result.updated":
        noteResults([data.result])
        break
      case "expertgranskning.finished":
        break
      default: {
        const _exhaustive: never = data
        return _exhaustive
      }
    }
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
          watchJobId.current = null
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

    try {
      const docId = await getOrCreateDocId()
      const latest = await getLatestWordJob(token, docId)
      const plan = planReviewStart(latest)
      switch (plan.action) {
        case "resume":
          attachWatch(plan.jobId, "resume")
          return
        case "startNew":
          break
        default: {
          const _exhaustive: never = plan
          return _exhaustive
        }
      }

      for (const commentId of plan.resolveCommentIds) {
        try {
          await resolveComment(commentId)
        } catch {
          // Already resolved or missing in this document.
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

      try {
        const jobId = await createWordJob(token, {
          panel_id: Number(panelId),
          doc_id: docId,
          word_session_id: WORD_SESSION_ID,
          sections,
          locale: locale === "en" ? "en" : "sv",
        })
        attachWatch(jobId, "new")
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          const again = await getLatestWordJob(token, docId)
          const retry = planReviewStart(again)
          if (retry.action === "resume") {
            attachWatch(retry.jobId, "resume")
            return
          }
        }
        throw err
      }
    } catch (err) {
      setPhase("failed")
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const canReview = Boolean(token && panelId) && phase !== "running"
  const runningStatus = watchSource === "resume" ? t("statusResume") : t("statusLive")

  return (
    <div className="pane">
      {phase === "running" ? (
        <div className="progress" role="progressbar" aria-label={t("reviewing")}>
          <span />
        </div>
      ) : null}

      <header className="pane-head">
        <div className="brand">
          <img
            src={headMark}
            alt=""
            className="brand-mark"
            width={25}
            height={40}
            draggable={false}
          />
          <div className="brand-copy">
            <h1>{t("title")}</h1>
            <p className="brand-name">{t("brandName")}</p>
          </div>
        </div>
        <label className="lang">
          <span className="vh">{t("language")}</span>
          <select
            className="lang-control"
            value={locale}
            onChange={(event) => setLocale(event.target.value === "en" ? "en" : "sv")}
          >
            <option value="sv">{t("languageSv")}</option>
            <option value="en">{t("languageEn")}</option>
          </select>
        </label>
      </header>

      <div className="pane-body">
        {token ? null : (
          <form className="stack" onSubmit={(event) => void handleSaveToken(event)}>
            <label htmlFor="token">{t("tokenLabel")}</label>
            <textarea
              id="token"
              rows={3}
              value={tokenDraft}
              onChange={(event) => setTokenDraft(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <p className="hint">{t("tokenHint")}</p>
            <button type="submit">{t("tokenSave")}</button>
          </form>
        )}

        <div className="field">
          <label htmlFor="panel">{t("panelLabel")}</label>
          <select
            id="panel"
            className="field-control"
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
          {phase === "running" ? (
            <>
              <span className="spinner" aria-hidden="true" />
              {t("reviewing")}
            </>
          ) : (
            t("review")
          )}
        </button>

        <p className="status" data-phase={phase} aria-live="polite">
          {phase === "idle" ? t("statusIdle") : null}
          {phase === "running" ? runningStatus : null}
          {phase === "done" ? t("statusDone") : null}
          {phase === "failed" ? t("statusFailed", { error }) : null}
        </p>
        {phase !== "failed" && error ? <p className="error">{error}</p> : null}
        {appliedCount > 0 && unplacedCount === 0 ? (
          <p className="hint">{t("appliedSummary", { applied: appliedCount })}</p>
        ) : null}
        {appliedCount === 0 && unplacedCount > 0 ? (
          <p className="hint">{t("unplacedSummary", { unplaced: unplacedCount })}</p>
        ) : null}
        {appliedCount > 0 && unplacedCount > 0 ? (
          <p className="hint">
            {t("applicationSummary", { applied: appliedCount, unplaced: unplacedCount })}
          </p>
        ) : null}

        {token ? (
          <div className="pane-foot">
            <button type="button" className="link" onClick={handleChangeToken}>
              {t("tokenChange")}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
