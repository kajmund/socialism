export function formatWhen(iso: string | null | undefined, locale: string, emDash: string): string {
  if (!iso) return emDash
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date)
}

export function attemptOrdinal(attemptIds: readonly string[], attemptId: string): number | null {
  const index = attemptIds.indexOf(attemptId)
  return index >= 0 ? index + 1 : null
}
