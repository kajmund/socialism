import type {
  BranchState,
  Injection,
  RunSummary,
  Tick,
  TickInterview,
} from "@/data/runs-types"
import type { MessageKey, TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

/** Fallback Swedish labels for surfaces not yet on useLocale (e.g. results panel). */
export const RUN_STATUS_LABEL: Record<RunSummary["status"], string> = {
  done: "Klar",
  running: "Pågår",
  draft: "Utkast",
  failed: "Misslyckad",
}

export const MEASUREMENT_IDS = [
  "opinion_snapshot",
  "sentiment_baseline",
  "phrase_propagation",
  "sentiment_recovery",
  "engagement_decay",
] as const

const MEASUREMENT_KEYS: Record<(typeof MEASUREMENT_IDS)[number], MessageKey> = {
  opinion_snapshot: "runs.measure.opinionSnapshot",
  sentiment_baseline: "runs.measure.sentimentBaseline",
  phrase_propagation: "runs.measure.phrasePropagation",
  sentiment_recovery: "runs.measure.sentimentRecovery",
  engagement_decay: "runs.measure.engagementDecay",
}

export function measurementLabel(id: string, t: Translate): string {
  if (id in MEASUREMENT_KEYS) {
    return t(MEASUREMENT_KEYS[id as (typeof MEASUREMENT_IDS)[number]])
  }
  return id
}

function cloneTick(t: Tick): Tick {
  return {
    ...t,
    key: "t" + Math.random().toString(36).slice(2, 8),
    injections: t.injections.map((inj) => ({
      ...inj,
      key: "i" + Math.random().toString(36).slice(2, 8),
    })),
    interviews: (t.interviews ?? []).map((iv) => ({
      ...iv,
      key: "iv" + Math.random().toString(36).slice(2, 8),
    })),
  }
}

function silentCopy(t: Tick): Tick {
  const copy = cloneTick(t)
  return { ...copy, silent: true, injections: [] }
}

/** Fork after tick `afterIndex`: A keeps injections, B is silent copy (control). */
export function makeStimulusControlBranch(
  mainTicks: Tick[],
  afterIndex: number,
): BranchState {
  const afterStem = mainTicks.slice(afterIndex + 1)
  const nextDay = mainTicks[afterIndex].day + 1
  const aTicks = afterStem.length > 0 ? afterStem.map(cloneTick) : [makeTick(nextDay)]
  const bTicks = aTicks.map(silentCopy)
  return { afterIndex, mode: "stimulus_control", a: aTicks, b: bTicks }
}

export function makeTick(day: number): Tick {
  return {
    key: "t" + Math.random().toString(36).slice(2, 8),
    day,
    silent: false,
    injections: [],
    rounds: 3,
    measurements: ["opinion_snapshot"],
    interviews: [],
  }
}

export function makeTickInterview(): TickInterview {
  return {
    key: "iv" + Math.random().toString(36).slice(2, 8),
    persona_id: "",
    prompt: "",
  }
}

/** Ensure ticks from API (older payloads) have interviews[]. */
export function normalizeTick(tick: Tick): Tick {
  return {
    ...tick,
    interviews: tick.interviews ?? [],
  }
}

export function normalizeTicks(ticks: Tick[]): Tick[] {
  return ticks.map(normalizeTick)
}

export function makeInjection(): Injection {
  return {
    key: "i" + Math.random().toString(36).slice(2, 8),
    type: "party_post",
    sender: "",
    text: "",
    mode: "text",
    url: "",
    fetching: false,
    sourceDomain: "",
    isVideo: false,
    message_id: null,
  }
}

export function extractDomain(url: string): string {
  try {
    const u = new URL(/^https?:\/\//.test(url) ? url : "https://" + url)
    return u.hostname.replace(/^www\./, "")
  } catch {
    return url.split("/")[0] ?? url
  }
}

export function looksLikeVideo(url: string): boolean {
  return /youtube\.com|youtu\.be|vimeo\.com/i.test(url)
}

export function formatRunDate(d: string, locale = "sv-SE"): string {
  return new Date(d).toLocaleDateString(locale, { day: "numeric", month: "short" })
}
