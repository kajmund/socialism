import type { Injection, Measurement, RunSummary, Tick } from "@/data/runs-types"

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

export function genSeed(): string {
  return Math.random().toString(36).slice(2, 10)
}

export function makeTick(day: number): Tick {
  return {
    key: "t" + Math.random().toString(36).slice(2, 8),
    day,
    silent: false,
    injections: [],
    rounds: 1,
    measurements: ["opinion_snapshot"],
  }
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
