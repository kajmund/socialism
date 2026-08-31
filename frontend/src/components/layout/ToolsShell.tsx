import { NavLink, Outlet, useLocation } from "react-router-dom"
import { AdminShell } from "@/components/layout/AdminShell"
import { useLocale, type MessageKey } from "@/i18n"
import { cn } from "@/lib/utils"

function isConfigurationEditorPath(pathname: string): boolean {
  return /^\/tools\/configurations\/(new|\d+\/edit)$/.test(pathname)
}

const TOOL_TABS: { key: MessageKey; to: string; end?: boolean }[] = [
  { key: "tools.tabConfigurations", to: "/tools/configurations" },
  { key: "tools.tabKunder", to: "/tools/kunder", end: true },
  { key: "tools.tabPanelCatalog", to: "/tools/panel-catalog", end: true },
  { key: "tools.tabAnchorSets", to: "/tools/anchor-sets" },
  { key: "tools.tabPlayground", to: "/tools/playground", end: true },
  { key: "tools.tabCache", to: "/tools/cache", end: true },
]

export function ToolsShell() {
  const { t } = useLocale()
  const { pathname } = useLocation()
  const hideToolsChrome = isConfigurationEditorPath(pathname)
  return (
    <AdminShell>
      <div className="wrap">
        {hideToolsChrome ? null : (
          <>
            <div className="head-row mb-2">
              <div>
                <h1>{t("tools.title")}</h1>
                <p className="muted">{t("tools.subtitle")}</p>
              </div>
            </div>
            <div
              role="tablist"
              aria-label={t("tools.tablistAria")}
              className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
            >
              {TOOL_TABS.map((tab) => (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  end={tab.end}
                  role="tab"
                  className={({ isActive }) =>
                    cn(
                      "-mb-px border-b-2 px-3 py-2 text-sm no-underline",
                      isActive
                        ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                        : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
                    )
                  }
                >
                  {t(tab.key)}
                </NavLink>
              ))}
            </div>
          </>
        )}
        <Outlet />
      </div>
    </AdminShell>
  )
}
