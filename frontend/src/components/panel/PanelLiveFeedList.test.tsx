import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { LocaleProvider } from "@/i18n"

import { PanelLiveFeedList } from "./PanelLiveFeedList"

describe("PanelLiveFeedList", () => {
  it("renders turn content as markdown, not pre-wrap text", () => {
    const html = renderToStaticMarkup(
      <LocaleProvider>
        <PanelLiveFeedList
          emptyLabel="empty"
          pendingTurn={null}
          turns={[
            {
              turn_id: "t1",
              speaker: "Anna",
              phase: "expert",
              content:
                "Detta är **fet** text och en lista:\n\n- Första punkten\n- Andra punkten\n\n*En kursiv kommentar.*\n\n[exempel](https://example.com)",
            },
          ]}
        />
      </LocaleProvider>,
    )

    expect(html).toContain("<strong>")
    expect(html).toContain("<ul>")
    expect(html).toContain("<em>")
    expect(html).toContain('href="https://example.com"')
    expect(html).not.toContain("whitespace-pre-wrap")
    expect(html).not.toContain("**fet**")
  })

  it("hides the next sub-question label until the moderator has asked it", () => {
    const html = renderToStaticMarkup(
      <LocaleProvider>
        <PanelLiveFeedList
          emptyLabel="empty"
          pendingTurn={{
            turn_id: "pending-2",
            speaker: "Anna",
            phase: "raise_hand",
            round_index: 2,
          }}
          turns={[
            {
              turn_id: "t-open",
              speaker: "moderator",
              phase: "opening",
              content: "Vi börjar med tonen.",
              round_index: 1,
            },
            {
              turn_id: "t-expert-1",
              speaker: "Anna",
              phase: "expert",
              content: "Tonen är för hård.",
              round_index: 1,
            },
          ]}
        />
      </LocaleProvider>,
    )

    expect(html).toContain("Delfråga 1")
    expect(html).not.toContain("Delfråga 2")
  })

  it("shows the sub-question label after the moderator has asked it", () => {
    const html = renderToStaticMarkup(
      <LocaleProvider>
        <PanelLiveFeedList
          emptyLabel="empty"
          pendingTurn={null}
          turns={[
            {
              turn_id: "t-q2",
              speaker: "moderator",
              phase: "sub_question",
              content: "Är fakta korrekta?",
              round_index: 2,
            },
            {
              turn_id: "t-expert-2",
              speaker: "Anna",
              phase: "expert",
              content: "Siffrorna stämmer.",
              round_index: 2,
            },
          ]}
        />
      </LocaleProvider>,
    )

    expect(html).toContain("Delfråga 2")
    expect(html).toContain("Är fakta korrekta?")
  })
})
