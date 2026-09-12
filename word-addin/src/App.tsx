import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"

import { ActionCard } from "@/components/ActionCard"
import headMark from "@/assets/devbrains-head.png"
import { useLocale } from "@/i18n/LocaleContext"
import { IntentInterviewCard } from "@/components/IntentInterview"
import {
  claimAction,
  completeAction,
  createWordJob,
  dismissAction,
  generateIntentInterview,
  getLatestWordJob,
  listExpertPanels,
  listWordActions,
  markActionUnresolved,
} from "@/lib/api"
import {
  newReviewBlock,
  sortedWordActions,
  upsertWordActions,
} from "@/lib/actionQueue"
import { applyPendingAction } from "@/lib/applyAction"
import { ApiError } from "@/lib/http"
import {
  commentsApiSupported,
  getOrCreateDocId,
  getStoredDocId,
  officeReady,
  paragraphStatesFromSnapshot,
  readDocumentParagraphs,
  resolveComment,
  WORD_SESSION_ID,
} from "@/lib/office"
import { resolveWordAnchor } from "@/lib/word/anchors"
import { executeWordAction } from "@/lib/word/executeWordAction"
import { clearStoredToken, getStoredToken, saveStoredToken } from "@/lib/tokenStorage"
import { finishedJobView, planReviewStart } from "@/lib/resume"
import { buildSections } from "@/lib/sections"
import {
  answersReady,
  isIntentInterviewInvalidError,
  normalizeIntentAnswers,
  setFreeTextAnswer,
  setSingleChoice,
  toggleMultiChoice,
} from "@/lib/intentInterview"
import {
  NoWordParagraphsError,
  NoWordSectionsError,
  prepareWordReview,
  submitPreparedWordReview,
} from "@/lib/startReview"
import { connectExpertgranskningWatch } from "@/lib/socket"
import type {
  DocumentIntentInterview,
  ExpertPanelSummary,
  IntentAnswer,
  WordAction,
  WordDocumentSection,
  WordTaskScopeType,
} from "@/lib/types"
import { actionsForWatchEvent, isWatchEvent } from "@/lib/watch"
import { createWordTask } from "@/lib/word/task"
import {
  captureWordTaskSnapshot,
  EmptyWordSelectionError,
  UnresolvedWordSelectionError,
  type WordTaskSnapshot,
} from "@/lib/word/taskSnapshot"

type Phase = "idle" | "preparing" | "interviewing" | "running" | "done" | "failed"

type ReviewDraft = {
  snapshot: WordTaskSnapshot
  sections: WordDocumentSection[]
  interview: DocumentIntentInterview
  answers: IntentAnswer[]
  index: number
  docId: string
  resolveCommentIds: string[]
}

export function App() {
  const { t, locale, setLocale } = useLocale()
  const [token, setToken] = useState("")
  const [tokenDraft, setTokenDraft] = useState("")
  const [panels, setPanels] = useState<ExpertPanelSummary[]>([])
  const [panelId, setPanelId] = useState("")
  const [reviewIntent, setReviewIntent] = useState("")
  const [taskScope, setTaskScope] = useState<WordTaskScopeType>("document")
  const [phase, setPhase] = useState<Phase>("idle")
  const [draft, setDraft] = useState<ReviewDraft | null>(null)
  const [watchSource, setWatchSource] = useState<"new" | "resume">("new")
  const [progress, setProgress] = useState<{
    sections_completed: number
    sections_total: number
  } | null>(null)
  const [error, setError] = useState("")
  const [actionsById, setActionsById] = useState<Map<string, WordAction>>(
    () => new Map(),
  )
  const [inFlightIds, setInFlightIds] = useState<Set<string>>(() => new Set())
  const [inWord, setInWord] = useState(false)
  const socketRef = useRef<{ close: () => void } | null>(null)
  const watchJobId = useRef<string | null>(null)
  const watchQueue = useRef(Promise.resolve())

  const actions = useMemo(() => sortedWordActions(actionsById), [actionsById])
  const reviewBlock = newReviewBlock(actions)

  function noteActions(rows: WordAction[]) {
    setActionsById((current) => upsertWordActions(current, rows))
  }

  function resetQueue() {
    setActionsById(new Map())
    setInFlightIds(new Set())
    setProgress(null)
  }

  function setBusy(actionId: string, busy: boolean) {
    setInFlightIds((current) => {
      const next = new Set(current)
      if (busy) next.add(actionId)
      else next.delete(actionId)
      return next
    })
  }

  async function reloadAction(jobId: string, actionId: string): Promise<WordAction | null> {
    const rows = await listWordActions(token, jobId)
    const match = rows.find((row) => row.id === actionId) ?? null
    if (match) noteActions([match])
    return match
  }

  function attachWatch(jobId: string, source: "new" | "resume") {
    if (watchJobId.current === jobId && socketRef.current) {
      setPhase("running")
      setWatchSource(source)
      return
    }
    socketRef.current?.close()
    socketRef.current = null
    if (watchJobId.current !== jobId) {
      resetQueue()
    }
    watchJobId.current = jobId
    setWatchSource(source)
    setPhase("running")
    socketRef.current = connectExpertgranskningWatch({
      token,
      jobId,
      onMessage(data) {
        watchQueue.current = watchQueue.current
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
        noteActions(finished.actions)
        setPhase(finished.phase)
        if (finished.phase === "failed") {
          setError(finished.error)
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
    setDraft(null)
    setPhase("idle")
    resetQueue()
  }

  async function applyWatchPayload(jobId: string, data: unknown) {
    if (!isWatchEvent(data) || data.job_id !== jobId) return
    for (const action of actionsForWatchEvent(data)) {
      switch (action.kind) {
        case "upsert":
          noteActions(action.actions)
          break
        case "progress":
          setProgress({
            sections_completed: action.sections_completed,
            sections_total: action.sections_total,
          })
          break
        case "finished":
          setProgress(null)
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

  async function handleApply(action: WordAction) {
    if (inFlightIds.has(action.id) || action.status !== "pending") return
    setBusy(action.id, true)
    setError("")
    try {
      const updated = await applyPendingAction(token, action.job_id, action, {
        readParagraphs: readDocumentParagraphs,
        paragraphStates: paragraphStatesFromSnapshot,
        resolveAnchor: resolveWordAnchor,
        wordSessionId: WORD_SESSION_ID,
        newApplicationId: () => crypto.randomUUID(),
        claimAction,
        executeWordAction,
        completeAction,
        markUnresolved: markActionUnresolved,
        reloadAction,
        rewritePrefix: t("rewritePrefix"),
      })
      noteActions([updated])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(action.id, false)
    }
  }

  async function handleDismiss(action: WordAction) {
    if (
      inFlightIds.has(action.id) ||
      (action.status !== "pending" && action.status !== "unresolved")
    ) {
      return
    }
    setBusy(action.id, true)
    setError("")
    try {
      const updated = await dismissAction(token, action.job_id, action.id)
      noteActions([updated])
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const latest = await reloadAction(action.job_id, action.id)
        if (latest) return
      }
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(action.id, false)
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
        case "blockUndecided":
          if (latest) noteActions(latest.actions)
          setError(t("blockUndecided"))
          return
        case "blockApplying":
          if (latest) noteActions(latest.actions)
          setError(t("blockApplying"))
          return
        case "startNew":
          break
        default: {
          const _exhaustive: never = plan
          return _exhaustive
        }
      }

      try {
        const prepared = await prepareWordReview({
          captureSnapshot: () => captureWordTaskSnapshot(taskScope),
          buildSections,
        })
        setPhase("preparing")
        const interview = await generateIntentInterview(token, {
          panel_id: Number(panelId),
          sections: prepared.sections,
          locale: locale === "en" ? "en" : "sv",
        })
        setDraft({
          snapshot: prepared.snapshot,
          sections: prepared.sections,
          interview,
          answers: [],
          index: 0,
          docId,
          resolveCommentIds: plan.resolveCommentIds,
        })
        setPhase("interviewing")
      } catch (err) {
        if (err instanceof EmptyWordSelectionError) {
          setPhase("idle")
          setError(t("emptySelection"))
          return
        }
        if (err instanceof UnresolvedWordSelectionError) {
          setPhase("idle")
          setError(t("unresolvedSelection"))
          return
        }
        if (err instanceof NoWordParagraphsError) {
          setPhase("idle")
          setError(t("noParagraphs"))
          return
        }
        if (err instanceof NoWordSectionsError) {
          setPhase("idle")
          setError(t("noSections"))
          return
        }
        if (isIntentInterviewInvalidError(err)) {
          setPhase("idle")
          setDraft(null)
          setError(t("interviewInvalid"))
          return
        }
        if (err instanceof ApiError && err.status === 409) {
          const again = await getLatestWordJob(token, docId)
          const retry = planReviewStart(again)
          switch (retry.action) {
            case "resume":
              attachWatch(retry.jobId, "resume")
              return
            case "blockUndecided":
              if (again) noteActions(again.actions)
              setError(t("blockUndecided"))
              return
            case "blockApplying":
              if (again) noteActions(again.actions)
              setError(t("blockApplying"))
              return
            case "startNew":
              break
            default: {
              const _exhaustive: never = retry
              return _exhaustive
            }
          }
        }
        setPhase("idle")
        setDraft(null)
        throw err
      }
    } catch (err) {
      setPhase("idle")
      setDraft(null)
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  function updateDraft(next: Partial<ReviewDraft>) {
    setDraft((current) => (current ? { ...current, ...next } : current))
  }

  function handleRestartInterview() {
    setDraft(null)
    setPhase("idle")
    setError("")
  }

  async function handleStartFromInterview() {
    if (!draft || !token || !panelId) return
    if (!answersReady(draft.interview, draft.answers)) return
    setError("")
    try {
      const jobId = await submitPreparedWordReview({
        snapshot: draft.snapshot,
        sections: draft.sections,
        createJob: ({ snapshot, sections }) =>
          createWordJob(token, {
            task: createWordTask({
              panelId: Number(panelId),
              scope: snapshot.scope,
            }),
            doc_id: draft.docId,
            word_session_id: WORD_SESSION_ID,
            sections,
            locale: locale === "en" ? "en" : "sv",
            review_intent: reviewIntent.trim(),
            intent_interview: draft.interview,
            intent_answers: normalizeIntentAnswers(draft.answers),
          }),
        async resolvePreviousComments() {
          for (const commentId of draft.resolveCommentIds) {
            try {
              await resolveComment(commentId)
            } catch {
              // Already resolved or missing in this document.
            }
          }
        },
      })
      setDraft(null)
      attachWatch(jobId, "new")
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const again = await getLatestWordJob(token, draft.docId)
        const retry = planReviewStart(again)
        switch (retry.action) {
          case "resume":
            setDraft(null)
            attachWatch(retry.jobId, "resume")
            return
          case "blockUndecided":
            if (again) noteActions(again.actions)
            setError(t("blockUndecided"))
            return
          case "blockApplying":
            if (again) noteActions(again.actions)
            setError(t("blockApplying"))
            return
          case "startNew":
            break
          default: {
            const _exhaustive: never = retry
            return _exhaustive
          }
        }
      }
      setPhase("interviewing")
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const canReview =
    Boolean(token && panelId) &&
    phase !== "running" &&
    phase !== "preparing" &&
    phase !== "interviewing" &&
    reviewBlock === null
  const interviewBusy = phase === "preparing"
  const runningStatus =
    progress != null
      ? t("statusProgress", {
          completed: progress.sections_completed,
          total: progress.sections_total,
        })
      : watchSource === "resume"
        ? t("statusResume")
        : t("statusLive")
  const reviewHint =
    phase !== "running" && reviewBlock === "applying"
      ? t("blockApplying")
      : phase !== "running" && reviewBlock === "undecided"
        ? t("blockUndecided")
        : null

  return (
    <div className="pane">
      {phase === "running" || phase === "preparing" ? (
        <div
          className="progress"
          role="progressbar"
          aria-label={phase === "preparing" ? t("statusPreparing") : runningStatus}
        >
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

        <fieldset className="scope">
          <legend>{t("scopeLabel")}</legend>
          <div className="scope-options">
            <label className="scope-option">
              <input
                type="radio"
                name="task-scope"
                value="document"
                checked={taskScope === "document"}
                onChange={() => setTaskScope("document")}
                disabled={!token || interviewBusy || phase === "interviewing"}
              />
              {t("scopeDocument")}
            </label>
            <label className="scope-option">
              <input
                type="radio"
                name="task-scope"
                value="selection"
                checked={taskScope === "selection"}
                onChange={() => setTaskScope("selection")}
                disabled={!token || interviewBusy || phase === "interviewing"}
              />
              {t("scopeSelection")}
            </label>
          </div>
          {taskScope === "selection" ? (
            <p className="hint">{t("scopeSelectionHint")}</p>
          ) : null}
        </fieldset>

        {phase === "interviewing" && draft ? (
          <IntentInterviewCard
            interview={draft.interview}
            answers={draft.answers}
            index={draft.index}
            canStart={answersReady(draft.interview, draft.answers)}
            t={t}
            onSelect={(questionId, value) =>
              updateDraft({ answers: setSingleChoice(draft.answers, questionId, value) })
            }
            onToggle={(questionId, value) =>
              updateDraft({ answers: toggleMultiChoice(draft.answers, questionId, value) })
            }
            onFreeText={(questionId, value) =>
              updateDraft({ answers: setFreeTextAnswer(draft.answers, questionId, value) })
            }
            onBack={() => updateDraft({ index: Math.max(0, draft.index - 1) })}
            onNext={() =>
              updateDraft({
                index: Math.min(draft.interview.questions.length - 1, draft.index + 1),
              })
            }
            onStart={() => void handleStartFromInterview()}
            onRestart={handleRestartInterview}
          />
        ) : (
          <button
            type="button"
            className="primary"
            disabled={!canReview}
            onClick={() => void handleReview()}
          >
            {phase === "running" || interviewBusy ? (
              <>
                <span className="spinner" aria-hidden="true" />
                {interviewBusy ? t("interviewGenerating") : t("reviewing")}
              </>
            ) : (
              t("review")
            )}
          </button>
        )}
        {phase === "interviewing" ? <p className="hint">{t("interviewHint")}</p> : null}

        <div className="field">
          <label htmlFor="intent">{t("intentLabel")}</label>
          <textarea
            id="intent"
            className="intent"
            rows={4}
            value={reviewIntent}
            onChange={(event) => setReviewIntent(event.target.value)}
            disabled={!token || phase === "running" || phase === "preparing"}
            placeholder={t("intentPlaceholder")}
          />
          <p className="hint">{t("intentHint")}</p>
        </div>

        <p className="status" data-phase={phase} aria-live="polite">
          {phase === "idle" ? t("statusIdle") : null}
          {phase === "preparing" ? t("statusPreparing") : null}
          {phase === "interviewing" ? t("statusInterview") : null}
          {phase === "running" ? runningStatus : null}
          {phase === "done" ? t("statusDone") : null}
          {phase === "failed" ? t("statusFailed", { error }) : null}
        </p>
        {phase !== "failed" && error ? <p className="error">{error}</p> : null}
        {reviewHint && !error ? <p className="error">{reviewHint}</p> : null}

        {actions.length > 0 ? (
          <section className="action-queue" aria-label={t("queueHeading")}>
            <h2>{t("queueHeading")}</h2>
            {actions.map((action) => (
              <ActionCard
                key={action.id}
                action={action}
                busy={inFlightIds.has(action.id)}
                onApply={(row) => void handleApply(row)}
                onDismiss={(row) => void handleDismiss(row)}
                t={t}
              />
            ))}
          </section>
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
