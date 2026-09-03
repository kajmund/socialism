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
})
