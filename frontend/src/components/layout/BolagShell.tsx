import { useMemo } from "react"
import { Outlet } from "react-router-dom"
import { AdminShell, type ShellNavItem } from "@/components/layout/AdminShell"
import type { ModuleComponentId } from "@/modules/manifest"
import { useKundModules } from "@/modules/useKundModules"

const BOLAG_NAV_ITEMS: ShellNavItem[] = [
  { key: "bolag.nav.experter", to: "/bolag/experter", match: "/bolag/experter" },
  { key: "bolag.nav.expertPanels", to: "/bolag/expertpaneler", match: "/bolag/expertpaneler" },
  { key: "bolag.nav.campaigns", to: "/bolag/campaigns", match: "/bolag/campaigns" },
  { key: "bolag.nav.reports", to: "/bolag/reports", match: "/bolag/reports" },
  { key: "bolag.nav.feedback", to: "/bolag/feedback", match: "/bolag/feedback" },
  { key: "bolag.nav.jobs", to: "/bolag/jobs", match: "/bolag/jobs", showActiveJobBadge: true },
]

function navComponent(match: string): ModuleComponentId | null {
  switch (match) {
    case "/bolag/experter":
      return "personas"
    case "/bolag/expertpaneler":
      return "panel_engine"
    case "/bolag/campaigns":
      return "campaigns"
    default:
      return null
  }
}

type BolagShellProps = {
  children?: React.ReactNode
}

/** Content wrapper for pages already rendered inside the /bolag layout route. */
export function NestedBolagPage({ children }: BolagShellProps) {
  return <>{children}</>
}

export function BolagShell({ children }: BolagShellProps) {
  const { manifests, loading } = useKundModules()
  const navItems = useMemo(() => {
    if (loading) return BOLAG_NAV_ITEMS
    return BOLAG_NAV_ITEMS.filter((item) => {
      const component = navComponent(item.match)
      if (component == null) return true
      return manifests.some((manifest) => manifest.components.includes(component))
    })
  }, [loading, manifests])
  return (
    <AdminShell
      navItems={navItems}
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
