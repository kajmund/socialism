import { NavLink, useLocation } from "react-router-dom"
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

const LINKS = [
  { label: "Personas", to: "/personas", match: "/personas" },
  { label: "Populationer", to: "/populations", match: "/populations" },
  { label: "Budskap", to: "/messages", match: "/messages" },
  { label: "Konfiguration", to: "/config", match: "/config" },
  { label: "Körningar", to: "/runs", match: "/runs" },
  { label: "Simulator", to: "/simulator", match: "/simulator" },
] as const

type AdminShellProps = {
  children: ReactNode
}

function isSectionActive(pathname: string, match: string) {
  return pathname === match || pathname.startsWith(`${match}/`)
}

export function AdminShell({ children }: AdminShellProps) {
  const { pathname } = useLocation()

  return (
    <div className="theme-admin">
      <header className="admin-topnav sticky top-0 z-50 bg-db-ink-950 text-db-ink-0">
        <div className="mx-auto flex max-w-[1240px] items-center justify-between gap-8 px-10 py-4">
          <NavLink to="/runs" className="admin-topnav-brand flex items-center gap-3 no-underline">
            <img
              src="/devbrains-logo-white.png"
              alt="Devbrains"
              className="h-7 w-auto"
            />
            <span className="hidden text-sm text-db-ink-0/70 lg:inline">
              Opinionssimulator
            </span>
          </NavLink>
          <nav className="flex items-center gap-7 text-sm" aria-label="Huvudmeny">
            {LINKS.map((link) => {
              const active = isSectionActive(pathname, link.match)
              return (
                <NavLink
                  key={link.to}
                  to={link.to}
                  className={cn(
                    "admin-topnav-link border-b-2 pb-0.5 no-underline transition-colors",
                    active
                      ? "is-active border-db-gold-500 text-db-ink-0"
                      : "border-transparent text-db-ink-0/75 hover:text-db-ink-0",
                  )}
                >
                  {link.label}
                </NavLink>
              )
            })}
          </nav>
        </div>
      </header>
      {children}
    </div>
  )
}
