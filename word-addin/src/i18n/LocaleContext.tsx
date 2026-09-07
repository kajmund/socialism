import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import {
  DEFAULT_LOCALE,
  type Locale,
  type MessageKey,
  translate,
} from "./messages"

const STORAGE_KEY = "socialism.word-addin.locale"

type LocaleContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: MessageKey, params?: Record<string, string | number>) => string
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

function readStoredLocale(): Locale {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === "sv" || raw === "en") return raw
  } catch {
    // ignore
  }
  return DEFAULT_LOCALE
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    const stored = readStoredLocale()
    document.documentElement.lang = stored
    return stored
  })
  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      setLocale(next) {
        setLocaleState(next)
        try {
          localStorage.setItem(STORAGE_KEY, next)
        } catch {
          // ignore
        }
        document.documentElement.lang = next
      },
      t: (key, params) => translate(locale, key, params),
    }),
    [locale],
  )
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext)
  if (!ctx) {
    throw new Error("useLocale must be used inside LocaleProvider")
  }
  return ctx
}
