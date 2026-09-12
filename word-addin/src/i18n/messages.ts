export const LOCALES = ["sv", "en"] as const
export type Locale = (typeof LOCALES)[number]
export const DEFAULT_LOCALE: Locale = "sv"

export const messages = {
  sv: {
    title: "Expertgranskning",
    brandName: "Devbrains",
    languageSv: "Svenska",
    languageEn: "English",
    tokenLabel: "Åtkomsttoken",
    tokenHint: "Klistra in token från inloggningslänken. Den sparas i tillägget.",
    tokenSave: "Spara token",
    tokenSaved: "Token sparad.",
    tokenEmpty: "Klistra in en token innan du sparar.",
    tokenPersistFailed: "Token används nu, men tillägget kunde inte spara den till nästa gång.",
    tokenChange: "Byt token",
    panelLabel: "Expertpanel",
    panelPlaceholder: "Välj panel",
    panelEmpty: "Inga expertpaneler syns för det här kontot.",
    intentLabel: "Granskningsavsikt",
    intentPlaceholder: "T.ex. Devbrains är motpart i avtalet.",
    intentHint:
      "Valfritt. Extra information till experterna om vad som ska analyseras, till exempel vilken part du företräder.",
    scopeLabel: "Omfattning",
    scopeDocument: "Hela dokumentet",
    scopeSelection: "Markering",
    scopeSelectionHint: "Markera stycken i dokumentet. Granska läser den aktuella markeringen.",
    emptySelection: "Markera minst ett stycke innan du granskar en markering.",
    unresolvedSelection: "Kunde inte koppla markeringen till dokumentets stycken.",
    review: "Granska",
    reviewing: "Granskar…",
    statusIdle: "Välj en panel och klicka Granska.",
    statusConnecting: "Startar granskning…",
    statusLive:
      "Förslag visas i sidopanelen. Tillämpa eller avfärda dem. Inget skrivs i dokumentet förrän du väljer Tillämpa.",
    statusResume:
      "Återanslöt till pågående granskning. Förslag visas i sidopanelen. Tillämpa eller avfärda dem.",
    statusDone:
      "Förslagsgenereringen är klar. Tillämpa eller avfärda kvarvarande förslag.",
    statusFailed: "Granskningen misslyckades: {error}",
    commentsUnsupported:
      "Den här Word-värden saknar insertComment (WordApi 1.4). Sidladda i Word-skrivbordet.",
    officeMissing: "Öppna tillägget i Word. Webbläsaren kan inte läsa dokumentet.",
    noParagraphs: "Dokumentet har inga stycken att granska.",
    noSections: "Kunde inte bygga en sektionsstruktur av dokumentet.",
    inserted: "Infogade kommentarer och omskrivningar: {count}",
    appliedSummary: "{applied} resultat applicerade",
    unplacedSummary:
      "{unplaced} kunde inte placeras säkert eftersom dokumentet ändrats.",
    applicationSummary:
      "{applied} resultat applicerade, {unplaced} kunde inte placeras säkert eftersom dokumentet ändrats.",
    rewritePrefix: "Föreslagen omskrivning:",
    language: "Språk",
    queueHeading: "Förslag",
    actionComment: "Kommentar",
    actionReplace: "Föreslagen ändring",
    actionCurrent: "Nuvarande",
    actionSuggested: "Förslag",
    actionWhy: "Varför",
    actionApply: "Tillämpa",
    actionDismiss: "Avfärda",
    actionApplying: "Tillämpas…",
    actionApplyingHint:
      "Tillämpningen är osäker. Dokumentet kan redan vara ändrat. Försök inte igen automatiskt.",
    actionApplied: "Tillämpad",
    actionDismissed: "Avfärdad",
    unresolvedStale: "Kunde inte placeras: dokumentet har ändrats.",
    unresolvedAmbiguous: "Kunde inte placeras: flera stycken matchar.",
    unresolvedMissing: "Kunde inte placeras: stycket saknas.",
    unresolvedUnsupported: "Kunde inte placeras: åtgärden stöds inte.",
    unresolvedUnknown: "Kunde inte placeras säkert.",
    blockUndecided:
      "Tillämpa eller avfärda öppna förslag innan du startar en ny granskning.",
    blockApplying:
      "Ett förslag håller på att tillämpas och resultatet i Word är osäkert. Starta inte en ny granskning.",
  },
  en: {
    title: "Expert review",
    brandName: "Devbrains",
    languageSv: "Svenska",
    languageEn: "English",
    tokenLabel: "Access token",
    tokenHint: "Paste the token from the magic-link sign-in. It is stored in the add-in.",
    tokenSave: "Save token",
    tokenSaved: "Token saved.",
    tokenEmpty: "Paste a token before saving.",
    tokenPersistFailed: "The token is in use now, but the add-in could not store it for next time.",
    tokenChange: "Change token",
    panelLabel: "Expert panel",
    panelPlaceholder: "Choose a panel",
    panelEmpty: "No expert panels are visible for this account.",
    intentLabel: "Review intent",
    intentPlaceholder: "E.g. Devbrains is the counterparty in the contract.",
    intentHint:
      "Optional. Extra information for the experts about what to analyse, for example which party you represent.",
    scopeLabel: "Scope",
    scopeDocument: "Whole document",
    scopeSelection: "Selection",
    scopeSelectionHint: "Select paragraphs in the document. Review reads the current selection.",
    emptySelection: "Select at least one paragraph before reviewing a selection.",
    unresolvedSelection: "Could not map the selection to document paragraphs.",
    review: "Review",
    reviewing: "Reviewing…",
    statusIdle: "Choose a panel and click Review.",
    statusConnecting: "Starting review…",
    statusLive:
      "Proposals appear in the pane. Apply or dismiss them. Nothing is written to the document until you choose Apply.",
    statusResume:
      "Reconnected to the running review. Proposals appear in the pane. Apply or dismiss them.",
    statusDone: "Proposal generation is finished. Apply or dismiss any remaining proposals.",
    statusFailed: "The review failed: {error}",
    commentsUnsupported:
      "This Word host does not support insertComment (WordApi 1.4). Sideload in Word desktop.",
    officeMissing: "Open the add-in in Word. The browser cannot read the document.",
    noParagraphs: "The document has no paragraphs to review.",
    noSections: "Could not build a section structure from the document.",
    inserted: "Comments and rewrites inserted: {count}",
    appliedSummary: "{applied} results applied",
    unplacedSummary: "{unplaced} could not be placed safely because the document changed.",
    applicationSummary:
      "{applied} results applied, {unplaced} could not be placed safely because the document changed.",
    rewritePrefix: "Suggested rewrite:",
    language: "Language",
    queueHeading: "Proposals",
    actionComment: "Comment",
    actionReplace: "Suggested edit",
    actionCurrent: "Current",
    actionSuggested: "Suggested",
    actionWhy: "Why",
    actionApply: "Apply",
    actionDismiss: "Dismiss",
    actionApplying: "Applying…",
    actionApplyingHint:
      "Application is uncertain. The document may already have changed. Do not retry automatically.",
    actionApplied: "Applied",
    actionDismissed: "Dismissed",
    unresolvedStale: "Could not be placed: the document has changed.",
    unresolvedAmbiguous: "Could not be placed: several paragraphs match.",
    unresolvedMissing: "Could not be placed: the paragraph is missing.",
    unresolvedUnsupported: "Could not be placed: this action is not supported.",
    unresolvedUnknown: "Could not be placed safely.",
    blockUndecided: "Apply or dismiss open proposals before starting a new review.",
    blockApplying:
      "A proposal is still applying and the Word outcome is uncertain. Do not start a new review.",
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
