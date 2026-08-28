import { Outlet } from "react-router-dom"
import { AdminShell, type ShellNavItem } from "@/components/layout/AdminShell"

const BOLAG_NAV_ITEMS: ShellNavItem[] = [
  { key: "bolag.nav.experter", to: "/bolag/experter", match: "/bolag/experter" },
  { key: "bolag.nav.expertPanels", to: "/bolag/expertpaneler", match: "/bolag/expertpaneler" },
  { key: "bolag.nav.campaigns", to: "/bolag/campaigns", match: "/bolag/campaigns" },
  { key: "bolag.nav.reports", to: "/bolag/reports", match: "/bolag/reports" },
  { key: "bolag.nav.feedback", to: "/bolag/feedback", match: "/bolag/feedback" },
  { key: "bolag.nav.jobs", to: "/bolag/jobs", match: "/bolag/jobs", showActiveJobBadge: true },
]

type BolagShellProps = {
  children?: React.ReactNode
}

/** Content wrapper for pages already rendered inside the /bolag layout route. */
export function NestedBolagPage({ children }: BolagShellProps) {
  return <>{children}</>
}

export function BolagShell({ children }: BolagShellProps) {
  return (
    <AdminShell
      navItems={BOLAG_NAV_ITEMS}
      brandTo="/bolag"
      navAriaLabelKey="bolag.nav.ariaMain"
      mobileMenuTitleKey="bolag.product"
      showTools={false}
      jobToasts
      customerScope="bolag"
      menuId="bolag-main-menu"
    >
      {children ?? <Outlet />}
    </AdminShell>
  )
}
