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
})
