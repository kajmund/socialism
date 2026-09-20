import { describe, expect, it } from "vitest"
import {
  citationFromLagenNuUrl,
  isLegalFrontMatter,
  legalSourceDisplay,
} from "./legalSourceDisplay"

describe("legalSourceDisplay", () => {
  it("turns a proposition cover page into a citation title without the header excerpt", () => {
    const display = legalSourceDisplay({
      title: "Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
      excerpt:
        "Regeringens proposition nr 6 år 1975 Prop. 1975:6 Nr 6 Regeringens proposition om ändring i konkurslagen (1921:225) m.m.; beslutad den 16 januari 1975.",
      source_url: "https://lagen.nu/prop/1975:6",
      provider: "lagen_nu",
    })
    expect(citationFromLagenNuUrl("https://lagen.nu/prop/1975:6")).toBe("Prop. 1975:6")
    expect(display.title).toBe("Prop. 1975:6 — Ändring i konkurslagen (1921:225)")
    expect(display.excerpt).toBeNull()
  })

  it("keeps a real body excerpt", () => {
    const display = legalSourceDisplay({
      title: "Prop. 1975:6 — Ändring i konkurslagen (1921:225)",
      excerpt:
        "Kungl. Maj:t föreslår riksdagen att anta ett nytt obeståndsbegrepp som knyter konkursförutsättningen till gäldenärens betalningsoförmåga.",
      source_url: "https://lagen.nu/prop/1975:6",
    })
    expect(display.excerpt).toContain("obeståndsbegrepp")
    expect(
      isLegalFrontMatter(
        "Regeringens proposition nr 6 år 1975 Prop. 1975:6 Nr 6",
        "Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
      ),
    ).toBe(true)
  })
})
