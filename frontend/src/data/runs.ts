import type {
  BranchState,
  Injection,
  Measurement,
  RunSummary,
  Tick,
  TickInterview,
} from "@/data/runs-types"

export const RUN_STATUS_LABEL: Record<RunSummary["status"], string> = {
  done: "Klar",
  running: "Pågår",
  draft: "Utkast",
  failed: "Misslyckad",
}

export const MEASUREMENTS: Measurement[] = [
  { id: "opinion_snapshot", label: "Opinionsmätning" },
  { id: "sentiment_baseline", label: "Sentiment-baslinje" },
  { id: "phrase_propagation", label: "Frasspridning" },
  { id: "sentiment_recovery", label: "Sentiment-återhämtning" },
  { id: "engagement_decay", label: "Engagemangsavklingning" },
]

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

export function formatRunDate(d: string): string {
  return new Date(d).toLocaleDateString("sv-SE", { day: "numeric", month: "short" })
}
