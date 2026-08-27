import { useEffect, useState, type ReactNode } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { useLocale } from "@/i18n"
import { cn } from "@/lib/utils"

type BolagShellProps = {
  children?: ReactNode
}

function MenuIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6z"
        />
      </svg>
    )
  }
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
      <rect x="4" y="8" width="22" height="2" fill="currentColor" />
      <rect x="4" y="14" width="22" height="2" fill="currentColor" />
      <rect x="4" y="20" width="22" height="2" fill="currentColor" />
    </svg>
  )
}

function SessionActions({ compact }: { compact?: boolean }) {
  const { t, locale, setLocale } = useLocale()
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  async function onSignOut() {
    await signOut()
    navigate("/login", { replace: true })
  }

  return (
    <div className={cn("flex items-center gap-4", compact && "flex-wrap")}>
      {user ? (
        <span className="text-xs text-white/70">
          {t("auth.signedInAs", { name: user.username })} · {t("auth.roleBolag")}
        </span>
      ) : null}
      <LocaleSwitcher locale={locale} setLocale={setLocale} t={t} />
      <button
        type="button"
        className="text-xs font-medium tracking-wide text-white/80 underline-offset-2 hover:text-white hover:underline"
        onClick={() => void onSignOut()}
      >
        {t("auth.signOut")}
      </button>
    </div>
  )
}

export function BolagShell({ children }: BolagShellProps) {
  const { t } = useLocale()
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    setMenuOpen(false)
  }, [pathname])

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1280px)")
    function sync() {
      if (desktop.matches) setMenuOpen(false)
    }
    sync()
    desktop.addEventListener("change", sync)
    return () => desktop.removeEventListener("change", sync)
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false)
    }
    window.addEventListener("keydown", onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prev
    }
  }, [menuOpen])

  const campaignsActive =
    pathname === "/bolag/campaigns" || pathname.startsWith("/bolag/campaigns/")

  return (
    <div className="theme-admin">
      <header className="admin-topnav relative sticky top-0 z-50 text-white">
        <div className="mx-auto flex h-[88px] max-w-[1440px] items-center justify-between gap-8 px-6 md:h-[100px] md:px-10 2xl:px-[90px]">
          <NavLink to="/bolag" className="admin-topnav-brand no-underline" onClick={() => setMenuOpen(false)}>
            <img src="/devbrains-logo-white.png" alt="Devbrains" className="h-10 w-auto md:h-[50px]" />
          </NavLink>
          <div className="hidden items-center gap-6 xl:flex">
            <nav className="flex items-center gap-6" aria-label={t("bolag.nav.ariaMain")}>
              <NavLink
                to="/bolag/campaigns"
                className={cn(
                  "admin-topnav-link admin-topnav-link-inline",
                  campaignsActive && "is-active",
                )}
              >
                {t("bolag.nav.campaigns")}
              </NavLink>
            </nav>
            <SessionActions />
          </div>
          <button
            type="button"
            className="admin-topnav-burger flex xl:hidden"
            aria-expanded={menuOpen}
            aria-controls="bolag-main-menu"
            aria-label={menuOpen ? t("nav.closeMenu") : t("nav.openMenu")}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MenuIcon open={menuOpen} />
          </button>
        </div>
        {menuOpen ? (
          <div
            id="bolag-main-menu"
            className="admin-topnav-panel absolute inset-x-0 top-full z-50 max-h-[calc(100vh-88px)] overflow-y-auto md:max-h-[calc(100vh-100px)] xl:hidden"
          >
            <div className="mx-auto flex max-w-[1440px] flex-col gap-8 px-6 py-10 md:px-10 md:py-12">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#fbd37b]">
                {t("bolag.product")}
              </p>
              <nav className="flex flex-col gap-4" aria-label={t("bolag.nav.ariaMain")}>
                <NavLink
                  to="/bolag/campaigns"
                  className={cn("admin-topnav-link admin-topnav-link-panel", campaignsActive && "is-active")}
                  onClick={() => setMenuOpen(false)}
                >
                  {t("bolag.nav.campaigns")}
                </NavLink>
              </nav>
              <SessionActions compact />
            </div>
          </div>
        ) : null}
      </header>
      {children ?? <Outlet />}
    </div>
  )
}
