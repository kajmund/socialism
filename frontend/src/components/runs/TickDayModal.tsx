import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Link } from "react-router-dom"
import {
  libraryTypeForInjection,
  listMessages,
  type Message,
} from "@/api/messages"
import { getCatalogList } from "@/api/catalog"
import { AdminButton } from "@/components/ui/admin-button"
import {
  CatalogLabelPicker,
  CatalogSenderEmptyHint,
  type CatalogLabelOption,
} from "@/components/runs/CatalogLabelPicker"
import { MessageLibraryPicker } from "@/components/runs/MessageLibraryPicker"
import { getPopulation } from "@/api/populations"
import {
  MEASUREMENT_IDS,
  makeInjection,
  makeTickInterview,
  measurementLabel,
} from "@/data/runs"
import type { Injection, Tick, TickInterview } from "@/data/runs-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

const INJECTION_TYPE_KEYS: Record<Injection["type"], MessageKey> = {
  party_post: "runs.tick.typeParty",
  news_post: "runs.tick.typeNews",
  ad_post: "runs.tick.typeAd",
}

function injectionTypeLabel(type: Injection["type"], t: Translate): string {
  return t(INJECTION_TYPE_KEYS[type])
}

function injectionSummary(inj: Injection, library: Message[], t: Translate): string {
  const parts = [injectionTypeLabel(inj.type, t)]
  if (inj.sender.trim()) parts.push(inj.sender.trim())
  const saved = inj.message_id
    ? library.find((m) => m.id === inj.message_id)
    : null
  if (saved?.title) {
    parts.push(saved.title)
  } else if (inj.text.trim()) {
    const snippet = inj.text.trim()
    parts.push(snippet.length > 48 ? `${snippet.slice(0, 48)}…` : snippet)
  } else {
    parts.push(t("runs.tick.noTextYet"))
  }
  return parts.join(" · ")
}

const ROUNDS_MIN = 1
const ROUNDS_SOFT_MAX = 12

type RoundsStepperProps = {
  value: number
  onChange: (n: number) => void
}

function normalizeRounds(value: number): number {
  if (!Number.isFinite(value)) return ROUNDS_MIN
  return Math.max(ROUNDS_MIN, Math.round(value))
}

function RoundsStepper({ value, onChange }: RoundsStepperProps) {
  const { t } = useLocale()
  const displayValue = normalizeRounds(value)
  const atSoftMax = displayValue >= ROUNDS_SOFT_MAX
  const openedValueRef = useRef(displayValue)

  const handleBlur = () => {
    if (displayValue < ROUNDS_MIN) {
      onChange(ROUNDS_MIN)
      return
    }
    if (
      displayValue > ROUNDS_SOFT_MAX &&
      displayValue !== openedValueRef.current
    ) {
      onChange(ROUNDS_SOFT_MAX)
    }
  }

  return (
    <div className="rounds-stepper">
      <button
        type="button"
        className="rounds-stepper-btn"
        onClick={() => onChange(displayValue - 1)}
        disabled={displayValue <= ROUNDS_MIN}
        aria-label={t("runs.tick.roundsDecrease")}
      >
        −
      </button>
      <input
        id="tick-rounds-input"
        className="rounds-stepper-input"
        type="number"
        min={ROUNDS_MIN}
        value={displayValue}
        onChange={(e) => {
          const parsed = parseInt(e.target.value, 10)
          if (!Number.isNaN(parsed)) onChange(parsed)
        }}
        onBlur={handleBlur}
        aria-label={t("runs.tick.roundsInputLabel")}
        aria-describedby="tick-rounds-hint"
      />
      <button
        type="button"
        className="rounds-stepper-btn"
        onClick={() => onChange(displayValue + 1)}
        disabled={atSoftMax}
        aria-label={t("runs.tick.roundsIncrease")}
      >
        +
      </button>
      <span className="rounds-num">
        {displayValue}{" "}
        {t(displayValue === 1 ? "runs.tick.roundOne" : "runs.tick.roundMany")}
      </span>
      <span id="tick-rounds-hint" className="rounds-stepper-hint">
        {t("runs.tick.roundsSoftMaxHint", { max: ROUNDS_SOFT_MAX })}
      </span>
    </div>
  )
}

type InjectionEditorProps = {
  inj: Injection
  onChange: (next: Injection) => void
  onRemove: () => void
  senderOptions: CatalogLabelOption[]
  expanded: boolean
  onToggle: () => void
}

function InjectionEditor({
  inj,
  onChange,
  onRemove,
  senderOptions,
  expanded,
  onToggle,
}: InjectionEditorProps) {
  const { t } = useLocale()
  const typeId = `inj-type-${inj.key}`
  const senderId = `inj-sender-${inj.key}`
  const libraryId = `inj-lib-${inj.key}`
  const textId = `inj-text-${inj.key}`

  const libraryType = libraryTypeForInjection(inj.type)
  const [library, setLibrary] = useState<Message[]>([])
  const [libError, setLibError] = useState<string | null>(null)
  const [scratchOpen, setScratchOpen] = useState(!inj.message_id && Boolean(inj.text))

  useEffect(() => {
    let cancelled = false
    listMessages({ type: libraryType })
      .then((data) => {
        if (!cancelled) {
          setLibrary(data)
          setLibError(null)
        }
      })
      .catch(() => {
        if (!cancelled) setLibError(t("runs.tick.libraryLoadError"))
      })
    return () => {
      cancelled = true
    }
  }, [libraryType])

  function selectLibraryMessage(messageId: string | null) {
    if (!messageId) {
      onChange({
        ...inj,
        message_id: null,
        text: "",
        url: "",
        sourceDomain: "",
        isVideo: false,
        fetching: false,
      })
      setScratchOpen(false)
      return
    }
    const msg = library.find((m) => m.id === messageId)
    if (!msg) return
    onChange({
      ...inj,
      message_id: msg.id,
      text: msg.body,
      url: msg.source_url ?? "",
      mode: "text",
      sourceDomain: "",
      isVideo: false,
      fetching: false,
    })
    setScratchOpen(false)
  }

  function enableScratch() {
    setScratchOpen(true)
    onChange({ ...inj, message_id: null })
  }

  return (
    <div className={"inj-event" + (expanded ? "" : " collapsed")}>
      <div className="inj-head">
        <button
          type="button"
          className="inj-head-toggle"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          <span className="inj-head-title">{injectionSummary(inj, library, t)}</span>
          <span className="inj-caret" aria-hidden>
            {expanded ? "▲" : "▼"}
          </span>
        </button>
        <button
          type="button"
          className="inj-remove"
          onClick={onRemove}
          title={t("runs.tick.removeEvent")}
        >
          ✕
        </button>
      </div>

      {expanded && (
        <div className="inj-body">
          <div className="inj-top">
            <div className="inj-field">
              <label htmlFor={typeId}>{t("runs.tick.typeLabel")}</label>
              <select
                id={typeId}
                value={inj.type}
                onChange={(e) =>
                  onChange({
                    ...inj,
                    type: e.target.value as Injection["type"],
                    message_id: null,
                  })
                }
              >
                <option value="party_post">{t("runs.tick.typeParty")}</option>
                <option value="news_post">{t("runs.tick.typeNews")}</option>
                <option value="ad_post">{t("runs.tick.typeAd")}</option>
              </select>
            </div>
          </div>

          <CatalogLabelPicker
            id={senderId}
            fieldLabel={t("runs.tick.senderLabel")}
            options={senderOptions}
            value={inj.sender}
            onChange={(sender) => onChange({ ...inj, sender })}
            placeholder={t("runs.tick.senderPlaceholder")}
            emptyHint={<CatalogSenderEmptyHint />}
          />

          <MessageLibraryPicker
            id={libraryId}
            messages={library}
            value={inj.message_id}
            onChange={selectLibraryMessage}
            error={libError}
            emptyHint={
              <>
                {t(
                  libraryType === "news"
                    ? "runs.tick.emptyNews"
                    : "runs.tick.emptyPosts",
                )}{" "}
                <Link to="/messages/new">{t("runs.tick.openWorkshop")}</Link>
              </>
            }
          />

          {inj.message_id && (
            <div className="inj-field">
              <label>{t("runs.tick.previewLabel")}</label>
              <textarea id={textId} value={inj.text} readOnly rows={4} />
            </div>
          )}

          <div className="inj-mode-switch">
            <button
              type="button"
              className={scratchOpen && !inj.message_id ? "on" : ""}
              onClick={enableScratch}
            >
              {t("runs.tick.scratchToggle")}
            </button>
          </div>

          {scratchOpen && !inj.message_id && (
            <div className="inj-field">
              <label htmlFor={textId}>
                {t("runs.tick.scratchLabel")}
              </label>
              <textarea
                id={textId}
                placeholder={t("runs.tick.scratchPlaceholder")}
                value={inj.text}
                onChange={(e) =>
                  onChange({ ...inj, message_id: null, text: e.target.value, mode: "text" })
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

type InterviewCandidate = { personaId: string; name: string }

export type DayModalTab = "injections" | "metrics" | "interviews"

type TickEditorBodyProps = {
  tick: Tick
  onUpdate: (next: Tick) => void
  populationId?: number | null
  initialTab?: DayModalTab
  /** When set, only these tabs are shown (e.g. interviews-only modal). */
  tabs?: DayModalTab[]
  /** Skip outer tl-body chrome when nested in an expanded day card. */
  embedded?: boolean
}

export function TickEditorBody({
  tick,
  onUpdate,
  populationId,
  initialTab = "injections",
  tabs,
  embedded = false,
}: TickEditorBodyProps) {
  const { t } = useLocale()
  const tabList: DayModalTab[] = tabs ?? ["injections", "metrics", "interviews"]
  const [senderOptions, setSenderOptions] = useState<CatalogLabelOption[]>([])
  const [activeTab, setActiveTab] = useState<DayModalTab>(
    tabList.includes(initialTab) ? initialTab : tabList[0]!,
  )
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set())
  const [candidates, setCandidates] = useState<InterviewCandidate[]>([])
  const interviews = tick.interviews ?? []

  useEffect(() => {
    setExpandedKeys(new Set())
    setActiveTab(
      tabList.includes(initialTab) ? initialTab : (tabList[0] ?? "injections"),
    )
    // Reset tab when switching day or modal focus — not on every tabList identity change.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tabList derived from tabs/initialTab
  }, [tick.key, initialTab, tabs])

  useEffect(() => {
    let cancelled = false
    getCatalogList("avsandare")
      .then((list) => {
        if (cancelled) return
        setSenderOptions(
          list.items.map((item) => ({
            label: item.label,
            description: item.description || undefined,
          })),
        )
      })
      .catch(() => {
        if (!cancelled) setSenderOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (populationId == null) {
      setCandidates([])
      return
    }
    let cancelled = false
    getPopulation(populationId)
      .then((pop) => {
        if (cancelled) return
        setCandidates(
          pop.members
            .filter((m) => Boolean(m.id))
            .map((m) => ({ personaId: m.id as string, name: m.name })),
        )
      })
      .catch(() => {
        if (!cancelled) setCandidates([])
      })
    return () => {
      cancelled = true
    }
  }, [populationId])

  function updateInj(i: number, next: Injection) {
    const arr = [...tick.injections]
    arr[i] = next
    onUpdate({ ...tick, injections: arr })
  }
  function addInj() {
    const inj = makeInjection()
    onUpdate({ ...tick, injections: [...tick.injections, inj] })
    setExpandedKeys((prev) => new Set([...prev, inj.key]))
  }
  function removeInj(i: number) {
    const key = tick.injections[i]?.key
    onUpdate({
      ...tick,
      injections: tick.injections.filter((_, idx) => idx !== i),
    })
    if (key) {
      setExpandedKeys((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }
  function toggleInjExpanded(key: string) {
    setExpandedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  function toggleMeas(id: string) {
    const has = tick.measurements.includes(id)
    onUpdate({
      ...tick,
      measurements: has
        ? tick.measurements.filter((m) => m !== id)
        : [...tick.measurements, id],
    })
  }
  function updateInterview(i: number, next: TickInterview) {
    const arr = [...interviews]
    arr[i] = next
    onUpdate({ ...tick, interviews: arr })
  }
  function addInterview() {
    const first = candidates[0]
    onUpdate({
      ...tick,
      interviews: [
        ...interviews,
        {
          ...makeTickInterview(),
          persona_id: first?.personaId ?? "",
        },
      ],
    })
  }
  function removeInterview(i: number) {
    onUpdate({
      ...tick,
      interviews: interviews.filter((_, idx) => idx !== i),
    })
  }

  const showTabs = tabList.length > 1

  return (
    <div
      className={embedded ? undefined : "tl-body"}
      style={embedded ? undefined : { borderTop: "none", padding: 0 }}
    >
      {showTabs ? (
        <div
          role="tablist"
          aria-label={t("runs.tick.tabsAria")}
          className="tick-modal-tabs mb-5 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
        >
          {(
            [
              { id: "injections" as const, label: t("runs.tick.tabInjections") },
              { id: "metrics" as const, label: t("runs.tick.tabMetrics") },
              { id: "interviews" as const, label: t("runs.tick.tabInterviews") },
            ] as const
          )
            .filter((tab) => tabList.includes(tab.id))
            .map((tab) => {
              const selected = tab.id === activeTab
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`tick-day-tab-${tab.id}`}
                  aria-selected={selected}
                  aria-controls={`tick-day-panel-${tab.id}`}
                  tabIndex={selected ? 0 : -1}
                  className={
                    selected
                      ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium text-[color:var(--text-body)]"
                      : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                  }
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tab.label}
                  {tab.id === "interviews" && interviews.length > 0
                    ? ` (${interviews.length})`
                    : ""}
                </button>
              )
            })}
        </div>
      ) : null}

      {activeTab === "injections" ? (
        <div
          role="tabpanel"
          id="tick-day-panel-injections"
          aria-labelledby="tick-day-tab-injections"
        >
          <div className="silent-toggle-row">
            <div>
              <div className="t">{t("runs.tick.silentTitle")}</div>
              <div className="s">
                {t("runs.tick.silentBody")}
              </div>
            </div>
            <button
              type="button"
              className={"toggle" + (tick.silent ? " on" : "")}
              onClick={() => onUpdate({ ...tick, silent: !tick.silent })}
              aria-pressed={tick.silent}
              aria-label={t("runs.tick.silentTitle")}
            />
          </div>

          {!tick.silent && (
            <div className="mt-5">
              <span className="tl-row-lbl">{t("runs.tick.injectionPhases")}</span>
              {tick.injections.map((inj, i) => (
                <InjectionEditor
                  key={inj.key}
                  inj={inj}
                  senderOptions={senderOptions}
                  expanded={expandedKeys.has(inj.key)}
                  onToggle={() => toggleInjExpanded(inj.key)}
                  onChange={(n) => updateInj(i, n)}
                  onRemove={() => removeInj(i)}
                />
              ))}
              <button type="button" className="add-inj-btn" onClick={addInj}>
                {t("runs.tick.addEvent")}
              </button>
            </div>
          )}
        </div>
      ) : activeTab === "metrics" ? (
        <div
          role="tabpanel"
          id="tick-day-panel-metrics"
          aria-labelledby="tick-day-tab-metrics"
        >
          <div>
            <span className="tl-row-lbl">
              {tick.silent
                ? t("runs.tick.roundsSilent")
                : t("runs.tick.roundsAfter")}
              <span className="tl-row-desc">
                {tick.silent
                  ? t("runs.tick.roundsSilentDesc")
                  : t("runs.tick.roundsAfterDesc")}
              </span>
            </span>
            <RoundsStepper
              key={tick.key}
              value={tick.rounds}
              onChange={(n) => onUpdate({ ...tick, rounds: n })}
            />
          </div>

          <div className="mt-6">
            <span className="tl-row-lbl">{t("runs.tick.measurements")}</span>
            <div className="meas-chips">
              {MEASUREMENT_IDS.map((id) => (
                <button
                  type="button"
                  key={id}
                  title={id}
                  className={
                    "meas-chip" + (tick.measurements.includes(id) ? " on" : "")
                  }
                  onClick={() => toggleMeas(id)}
                  aria-pressed={tick.measurements.includes(id)}
                >
                  {measurementLabel(id, t)}
                  <span className="mid">{id}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div
          role="tabpanel"
          id="tick-day-panel-interviews"
          aria-labelledby="tick-day-tab-interviews"
        >
          <p className="mb-4 text-sm text-muted-foreground">
            {t("runs.tick.interviewsIntro")}
          </p>
          {candidates.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {populationId == null
                ? t("runs.tick.interviewsNeedPop")
                : t("runs.tick.interviewsNoMembers")}
            </p>
          ) : null}
          <div className="space-y-3">
            {interviews.map((iv, i) => (
              <div
                key={iv.key || `iv-${i}`}
                className="rounded-md border border-[color:var(--border-hairline)] p-3"
              >
                <label className="mb-1 block text-xs text-muted-foreground">
                  {t("runs.tick.personaLabel")}
                </label>
                <select
                  className="mb-3 w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm"
                  value={iv.persona_id}
                  onChange={(e) =>
                    updateInterview(i, { ...iv, persona_id: e.target.value })
                  }
                >
                  <option value="">{t("runs.tick.pickPersona")}</option>
                  {candidates.map((c) => (
                    <option key={c.personaId} value={c.personaId}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <label className="mb-1 block text-xs text-muted-foreground">
                  {t("runs.tick.questionLabel")}
                </label>
                <textarea
                  className="mb-2 w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm"
                  rows={3}
                  value={iv.prompt}
                  placeholder={t("runs.tick.questionPlaceholder")}
                  onChange={(e) =>
                    updateInterview(i, { ...iv, prompt: e.target.value })
                  }
                />
                <button
                  type="button"
                  className="text-xs text-destructive hover:underline"
                  onClick={() => removeInterview(i)}
                >
                  {t("common.delete")}
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="add-inj-btn mt-3"
            onClick={addInterview}
            disabled={candidates.length === 0}
          >
            {t("runs.tick.addInterview")}
          </button>
        </div>
      )}
    </div>
  )
}

type TickDayModalProps = {
  open: boolean
  tick: Tick | null
  onUpdate: (next: Tick) => void
  onClose: () => void
  populationId?: number | null
  initialTab?: DayModalTab
  tabs?: DayModalTab[]
  title?: string
  subtitle?: string
}

export function TickDayModal({
  open,
  tick,
  onUpdate,
  onClose,
  populationId = null,
  initialTab = "injections",
  tabs,
  title,
  subtitle,
}: TickDayModalProps) {
  const { t } = useLocale()
  const overlayMouseDownRef = useRef(false)

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open || !tick) return null

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tick-day-modal-title"
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div className="flex max-h-[min(880px,92vh)] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <div>
            <h2 id="tick-day-modal-title" className="text-base font-medium">
              {title ?? t("runs.timeline.dayLabel", { day: tick.day })}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {subtitle ?? t("runs.tick.defaultSubtitle")}
            </p>
          </div>
          <button
            type="button"
            className="tl-icon-btn shrink-0 text-lg"
            onClick={onClose}
            aria-label={t("common.close")}
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <TickEditorBody
            tick={tick}
            onUpdate={onUpdate}
            populationId={populationId}
            initialTab={initialTab}
            tabs={tabs}
          />
        </div>
        <div className="flex justify-end gap-2 border-t border-[color:var(--border-hairline)] px-5 py-4">
          <AdminButton variant="primary" onClick={onClose}>
            {t("common.done")}
          </AdminButton>
        </div>
      </div>
    </div>,
    document.body,
  )
}
