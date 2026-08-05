export const LOCALES = ["sv", "en"] as const

export type Locale = (typeof LOCALES)[number]

export const DEFAULT_LOCALE: Locale = "sv"

export const LOCALE_STORAGE_KEY = "opinionssimulator.locale"

export const LOCALE_LABELS: Record<Locale, string> = {
  sv: "Svenska",
  en: "English",
}

/** BCP 47 tag for Intl date/number formatting. */
export function intlLocale(locale: Locale): string {
  switch (locale) {
    case "sv":
      return "sv-SE"
    case "en":
      return "en-GB"
    default: {
      const _exhaustive: never = locale
      return _exhaustive
    }
  }
}

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value)
}

export function readStoredLocale(): Locale {
  try {
    const raw = localStorage.getItem(LOCALE_STORAGE_KEY)
    if (raw && isLocale(raw)) return raw
  } catch {
    // ignore quota / private mode
  }
  return DEFAULT_LOCALE
}

export function writeStoredLocale(locale: Locale): void {
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // ignore
  }
}
