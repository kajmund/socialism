export const LOCALES = ["sv", "en"] as const
export type Locale = (typeof LOCALES)[number]
export const DEFAULT_LOCALE: Locale = "sv"

export const messages = {
  sv: {
    title: "Expertgranskning",
    tokenLabel: "Åtkomsttoken",
    tokenHint: "Klistra in token från inloggningslänken. Den sparas i Word.",
    tokenSave: "Spara token",
    tokenSaved: "Token sparad.",
    panelLabel: "Expertpanel",
    panelPlaceholder: "Välj panel",
    panelEmpty: "Inga expertpaneler syns för det här kontot.",
    review: "Granska",
    reviewing: "Granskar…",
    statusIdle: "Välj en panel och klicka Granska.",
    statusConnecting: "Startar granskning…",
    statusLive: "Kommentarer kommer in i dokumentet.",
    statusDone: "Granskningen är klar.",
    statusFailed: "Granskningen misslyckades: {error}",
    commentsUnsupported:
      "Den här Word-värden saknar insertComment (WordApi 1.4). Sidladda i Word-skrivbordet.",
    officeMissing: "Öppna tillägget i Word. Webbläsaren kan inte läsa dokumentet.",
    noParagraphs: "Dokumentet har inga stycken att granska.",
    noSections: "Kunde inte bygga en sektionsstruktur av dokumentet.",
    inserted: "Infogade kommentarer: {count}",
    language: "Språk",
  },
  en: {
    title: "Expert review",
    tokenLabel: "Access token",
    tokenHint: "Paste the token from the magic-link sign-in. It is stored in Word.",
    tokenSave: "Save token",
    tokenSaved: "Token saved.",
    panelLabel: "Expert panel",
    panelPlaceholder: "Choose a panel",
    panelEmpty: "No expert panels are visible for this account.",
    review: "Review",
    reviewing: "Reviewing…",
    statusIdle: "Choose a panel and click Review.",
    statusConnecting: "Starting review…",
    statusLive: "Comments are appearing in the document.",
    statusDone: "The review is finished.",
    statusFailed: "The review failed: {error}",
    commentsUnsupported:
      "This Word host does not support insertComment (WordApi 1.4). Sideload in Word desktop.",
    officeMissing: "Open the add-in in Word. The browser cannot read the document.",
    noParagraphs: "The document has no paragraphs to review.",
    noSections: "Could not build a section structure from the document.",
    inserted: "Comments inserted: {count}",
    language: "Language",
  },
} as const

export type MessageKey = keyof typeof messages.sv

export function translate(
  locale: Locale,
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  let raw: string = messages[locale][key] ?? messages.sv[key]
  if (!params) return raw
  return raw.replace(/\{(\w+)\}/g, (_, name: string) =>
    params[name] != null ? String(params[name]) : `{${name}}`,
  )
}
