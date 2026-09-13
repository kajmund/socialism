import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { IntentInterviewCard } from "./IntentInterview"
import { translate } from "@/i18n/messages"
import { selectOtherAnswer, setSingleChoice } from "@/lib/intentInterview"
import type { DocumentIntentInterview, IntentAnswer, IntentQuestion } from "@/lib/types"

const party: IntentQuestion = {
  id: "party",
  text: "Vilken part företräder du?",
  type: "single_choice",
  required: true,
  rationale: "Partsställning ändrar analysen.",
  options: [
    { value: "buyer", label: "Köpare" },
    { value: "seller", label: "Säljare" },
  ],
}

const interview: DocumentIntentInterview = {
  document_type: "pleading",
  questions: [party],
}

function renderCard(answers: IntentAnswer[]): string {
  return renderToStaticMarkup(
    <IntentInterviewCard
      interview={interview}
      answers={answers}
      index={0}
      canStart={answers.length > 0 && Boolean(answers[0]?.selected_values.length || answers[0]?.free_text?.trim())}
      t={(key, params) => translate("sv", key, params)}
      onSelect={() => undefined}
      onToggle={() => undefined}
      onFreeText={() => undefined}
      onSelectOther={() => undefined}
      onOtherText={() => undefined}
      onBack={() => undefined}
      onNext={() => undefined}
      onStart={() => undefined}
      onRestart={() => undefined}
    />,
  )
}

describe("IntentInterviewCard start button", () => {
  it("keeps Granska visible and disabled until the required answer is complete", () => {
    const html = renderCard([])
    expect(html).toContain("Granska")
    expect(html).toContain("disabled")
    expect(html).toContain("Annat / Inget av ovanstående")
    expect(html).not.toContain("Starta granskning")
    expect(html).not.toContain("Skriv ditt svar")
  })

  it("enables Granska when a generated option is selected", () => {
    const html = renderCard(setSingleChoice([], "party", "buyer"))
    expect(html).toContain("Granska")
    expect(html).not.toMatch(/<button[^>]*class="primary"[^>]*disabled/)
  })

  it("reveals free text when other is selected and stays incomplete until text exists", () => {
    const other = selectOtherAnswer([], "party")
    const html = renderCard(other)
    expect(html).toContain("Annat / Inget av ovanstående")
    expect(html).toContain("Skriv ditt svar")
    expect(html).toContain("disabled")
  })
})
