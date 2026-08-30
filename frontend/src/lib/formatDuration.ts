import type { MessageKey, TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

function parseStamp(iso: string): number {
  const trimmed = iso.trim()
  if (!trimmed) return Number.NaN
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(trimmed)
  const normalized = hasZone
    ? trimmed
    : trimmed.includes("T")
      ? `${trimmed}Z`
      : `${trimmed.replace(" ", "T")}Z`
  return new Date(normalized).getTime()
}

export function formatElapsed(
  startIso: string | null | undefined,
  endIso: string | null | undefined,
  t: Translate,
  prefix: "reports.duration" | "jobs.duration",
): string | null {
  if (!startIso || !endIso) return null
  const ms = parseStamp(endIso) - parseStamp(startIso)
  if (!Number.isFinite(ms) || ms < 1000) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return t(`${prefix}.seconds`, { n: sec })
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) {
    return s > 0
      ? t(`${prefix}.minutesSeconds`, { m, s })
      : t(`${prefix}.minutes`, { m })
  }
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? t(`${prefix}.hoursMinutes`, { h, m: rm }) : t(`${prefix}.hours`, { h })
}
