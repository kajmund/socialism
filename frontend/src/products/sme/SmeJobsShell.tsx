import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { useLocale } from "@/i18n"
import { SmeUserMenu } from "@/products/sme/SmeUserMenu"

export function SmeJobsShell({ children }: { children: ReactNode }) {
  const { locale, setLocale, t } = useLocale()
  return (
    <div className="theme-admin flex h-dvh min-h-0 flex-col bg-db-ink-50 font-sans text-[color:var(--text-body)]">
      <header className="flex h-16 shrink-0 items-center bg-db-ink-950 px-4 text-db-ink-0 sm:px-6">
        <img
          src="/devbrains-logo-white.png"
          alt="Devbrains"
          className="h-8 w-auto"
        />
        <span className="mx-4 h-6 w-px bg-white/20" aria-hidden="true" />
        <Link
          to="/"
          className="font-[var(--font-display)] text-sm font-medium tracking-wide text-white/80 hover:text-white"
        >
          {t("sme.back")}
        </Link>
        <span className="mx-3 text-white/40" aria-hidden="true">
          /
        </span>
        <span className="font-[var(--font-display)] text-sm font-medium tracking-wide text-white">
          {t("sme.jobs")}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <LocaleSwitcher locale={locale} setLocale={setLocale} t={t} />
          <SmeUserMenu />
        </div>
      </header>
      <div className="admin-main-scroll min-h-0 flex-1 overflow-auto">
        {children}
      </div>
    </div>
  )
}
