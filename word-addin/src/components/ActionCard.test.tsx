import type { ReactElement, ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

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

type ClickableProps = {
  children?: ReactNode
  className?: string
  onClick?: (event: { stopPropagation: () => void }) => void
}

function findElement(
  node: ReactNode,
  predicate: (element: ReactElement<ClickableProps>) => boolean,
): ReactElement<ClickableProps> | null {
  if (node == null || typeof node !== "object") return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = findElement(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!("type" in node) || !("props" in node)) return null
  const element = node as ReactElement<ClickableProps>
  if (predicate(element)) return element
  return findElement(element.props.children, predicate)
}

function clickEvent() {
  return {
    stopped: false,
    stopPropagation() {
      this.stopped = true
    },
  }
}

describe("ActionCard Why click vs card select", () => {
  it("does not call onSelect when Varför? or Why? is clicked, but card body still does", () => {
    const onSelect = vi.fn()
    const onApply = vi.fn()
    const onDismiss = vi.fn()
    for (const locale of ["sv", "en"] as const) {
      onSelect.mockClear()
      const row = action()
      const tree = ActionCard({
        action: row,
        busy: false,
        onSelect,
        onApply,
        onDismiss,
        t: (key, params) => translate(locale, key, params),
      })
      const summary = findElement(tree, (element) => element.type === "summary")
      expect(summary).not.toBeNull()
      expect(summary?.props.children).toBe(locale === "sv" ? "Varför?" : "Why?")
      const whyClick = clickEvent()
      summary?.props.onClick?.(whyClick)
      expect(whyClick.stopped).toBe(true)
      expect(onSelect).not.toHaveBeenCalled()
      expect(onApply).not.toHaveBeenCalled()
      expect(onDismiss).not.toHaveBeenCalled()

      const details = findElement(
        tree,
        (element) => element.type === "details" && element.props.className === "action-card-why",
      )
      const detailsClick = clickEvent()
      details?.props.onClick?.(detailsClick)
      expect(detailsClick.stopped).toBe(true)
      expect(onSelect).not.toHaveBeenCalled()

      const article = tree as ReactElement<{ onClick?: () => void }>
      article.props.onClick?.()
      expect(onSelect).toHaveBeenCalledTimes(1)
      expect(onSelect).toHaveBeenCalledWith(row)
    }
  })
})

