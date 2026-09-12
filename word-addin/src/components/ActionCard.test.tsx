import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ActionCard } from "./ActionCard"
import { translate } from "@/i18n/messages"
import type { WordAction } from "@/lib/types"

function action(overrides: Partial<WordAction> = {}): WordAction {
  return {
    id: "wa_1",
    job_id: "job_1",
    action_type: "comment",
    content: "Anna: Skärp ingressen.",
    explanation: "Formuleringen saknar ett konkret åtagande.",
    status: "pending",
    created_at: "2026-09-12T10:00:00+00:00",
    ...overrides,
  }
}

describe("ActionCard comment explanation", () => {
  it("keeps the Why details collapsed until opened", () => {
    const html = renderToStaticMarkup(
      <ActionCard
        action={action()}
        busy={false}
        onApply={() => undefined}
        onDismiss={() => undefined}
        t={(key, params) => translate("sv", key, params)}
      />,
    )
    expect(html).toContain("Anna: Skärp ingressen.")
    expect(html).toContain("Varför?")
    expect(html).toContain("Formuleringen saknar ett konkret åtagande.")
    expect(html).toContain("<details")
    expect(html).not.toContain("<details open")
    expect(html).toContain("Tillämpa")
    expect(html).toContain("Avfärda")
  })

  it("omits the Why control when a comment has no explanation", () => {
    const html = renderToStaticMarkup(
      <ActionCard
        action={action({ explanation: null })}
        busy={false}
        onApply={() => undefined}
        onDismiss={() => undefined}
        t={(key, params) => translate("sv", key, params)}
      />,
    )
    expect(html).toContain("Anna: Skärp ingressen.")
    expect(html).not.toContain("<details")
    expect(html).not.toContain("Varför?")
  })

  it("marks the clicked card as selected", () => {
    const html = renderToStaticMarkup(
      <ActionCard
        action={action()}
        busy={false}
        selected
        onSelect={() => undefined}
        onApply={() => undefined}
        onDismiss={() => undefined}
        t={(key, params) => translate("sv", key, params)}
      />,
    )
    expect(html).toContain('data-selected="true"')
    expect(html).toContain('aria-current="true"')
  })

  it("shows a localized missing location without a Why control", () => {
    const html = renderToStaticMarkup(
      <ActionCard
        action={action({ explanation: null })}
        busy={false}
        selected
        locationError="missing"
        onSelect={() => undefined}
        onApply={() => undefined}
        onDismiss={() => undefined}
        t={(key, params) => translate("sv", key, params)}
      />,
    )
    expect(html).toContain("Kunde inte placeras: stycket saknas.")
    expect(html).toContain('data-unresolved-reason="missing"')
    expect(html).toContain('data-location-error="missing"')
    expect(html).not.toContain("Varför?")
  })

  it("shows localized stale and ambiguous location errors", () => {
    const stale = renderToStaticMarkup(
      <ActionCard
        action={action()}
        busy={false}
        locationError="stale"
        onApply={() => undefined}
        onDismiss={() => undefined}
        t={(key, params) => translate("sv", key, params)}
      />,
    )
    const ambiguous = renderToStaticMarkup(
      <ActionCard
        action={action()}
        busy={false}
        locationError="ambiguous"
        onApply={() => undefined}
        onDismiss={() => undefined}
        t={(key, params) => translate("en", key, params)}
      />,
    )
    expect(stale).toContain("Kunde inte placeras: dokumentet har ändrats.")
    expect(stale).toContain("<details")
    expect(stale).not.toContain("<details open")
    expect(ambiguous).toContain("Could not be placed: several paragraphs match.")
  })
})
