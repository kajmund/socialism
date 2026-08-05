import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react"
import {
  DEFAULT_LOCALE,
  intlLocale,
  readStoredLocale,
  writeStoredLocale,
  type Locale,
} from "./locales"
import { createTranslator, type MessageKey, type TranslateParams } from "./t"

type LocaleContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: MessageKey, params?: TranslateParams) => string
  intl: string
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

function subscribeLocale(onStoreChange: () => void) {
  const handler = (event: StorageEvent) => {
    if (event.key === null || event.key === "opinionssimulator.locale") onStoreChange()
  }
  window.addEventListener("storage", handler)
  return () => window.removeEventListener("storage", handler)
}

function getLocaleSnapshot(): Locale {
  return readStoredLocale()
}

function getServerLocaleSnapshot(): Locale {
  return DEFAULT_LOCALE
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const stored = useSyncExternalStore(
    subscribeLocale,
    getLocaleSnapshot,
    getServerLocaleSnapshot,
  )
  const [locale, setLocaleState] = useState<Locale>(stored)

  useEffect(() => {
    setLocaleState(stored)
  }, [stored])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const value = useMemo<LocaleContextValue>(() => {
    const t = createTranslator(locale)
    return {
      locale,
      setLocale: (next) => {
        writeStoredLocale(next)
        setLocaleState(next)
      },
      t,
      intl: intlLocale(locale),
    }
  }, [locale])

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext)
  if (!ctx) {
    throw new Error("useLocale must be used within LocaleProvider")
  }
  return ctx
}
