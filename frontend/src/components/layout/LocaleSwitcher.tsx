import type { Locale, MessageKey } from "@/i18n"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

export function LocaleSwitcher({
  locale,
  setLocale,
  t,
}: {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: Translate
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-white/70">
      <span className="sr-only">{t("locale.switcherLabel")}</span>
      <select
        className="rounded border border-white/25 bg-black/40 px-3 py-1.5 text-sm text-white"
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        aria-label={t("locale.switcherLabel")}
      >
        <option value="sv">{t("locale.sv")}</option>
        <option value="en">{t("locale.en")}</option>
      </select>
    </label>
  )
}
