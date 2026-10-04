import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { LocaleProvider } from "@/i18n"
import { SmeExpertInterviewButton } from "./SmeExpertInterviewButton"

const auth = vi.hoisted(() => ({ customerId: 7 as number | null }))
vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { kundId: auth.customerId, product: "sme" }, loading: false }),
}))

function render(workspaceKind: "company" | "client", customerId?: number) {
  return renderToStaticMarkup(<LocaleProvider><SmeExpertInterviewButton
    expertId="expert-a" expertName="Anna" workspaceKind={workspaceKind} customerId={customerId} beforeOpen={async () => undefined}
  /></LocaleProvider>)
}

describe("company expert interview access", () => {
  beforeEach(() => { auth.customerId = 7 })

  it("provides an embedded entry for SME users without an admin route", () => {
    const html = render("company")
    expect(html).toContain('aria-label="Öppna företagets expertintervju med Anna"')
    expect(html).not.toContain("href=")
    expect(html).not.toContain("disabled=")
  })

  it("does not put company interview history inside a client workspace", () => {
    expect(render("client")).toBe("")
  })

  it("requires a company context and accepts an explicit customer for an admin", () => {
    auth.customerId = null
    expect(render("company")).toContain("disabled=")
    expect(render("company", 12)).not.toContain("disabled=")
  })
})
