import { useState, type FormEvent } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { homePathForUser } from "@/lib/auth"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { useLocale } from "@/i18n"

type LoginLocationState = {
  from?: string
}

export function LoginPage() {
  const { t, locale, setLocale } = useLocale()
  const { session, loading, requestMagicLink, resolvedModules, profileError } = useAuth()
  const location = useLocation()
  const from = (location.state as LoginLocationState | null)?.from
  const [email, setEmail] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [linkSent, setLinkSent] = useState(false)
  const noModules = Boolean(session) && resolvedModules.length === 0

  const profileErrorMessage =
    profileError === "not_provisioned"
      ? t("auth.notProvisioned")
      : profileError === "invalid_token"
        ? t("auth.invalidToken")
        : profileError === "unknown"
          ? t("auth.profileFailed")
          : null

  if (loading) return <div className="min-h-svh bg-db-black" aria-hidden="true" />
  if (session && resolvedModules.length > 0) {
    const dest =
      from && from !== "/login" && from !== "/valj-modul"
        ? from
        : homePathForUser(resolvedModules)
    return <Navigate to={dest} replace />
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await requestMagicLink(email)
      setLinkSent(true)
    } catch {
      setError(t("auth.magicLinkFailed"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative min-h-svh overflow-hidden bg-db-black text-white">
      <img
        src="/login/villa-devbrains.jpg"
        alt={t("auth.backgroundAlt")}
        className="absolute inset-0 h-full w-full object-cover object-[center_42%]"
      />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-[0.18] mix-blend-overlay"
        style={{ backgroundImage: "url('/login/pattern.jpg')" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-black/50" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-gradient-to-b from-black/55 via-black/25 to-black/75"
        aria-hidden="true"
      />
      <div
        className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-db-gold-500/80 to-transparent"
        aria-hidden="true"
      />

      <div className="relative z-10 flex min-h-svh flex-col">
        <header className="flex items-center justify-between px-6 py-6 md:px-10">
          <img
            src="/devbrains-logo-white.png"
            alt={t("auth.logoAlt")}
            className="h-9 w-auto md:h-11"
          />
          <LocaleSwitcher locale={locale} setLocale={setLocale} t={t} />
        </header>

        <main className="flex flex-1 items-center justify-center px-4 pb-16">
          <div className="relative w-full max-w-[420px]">
            <div
              className="pointer-events-none absolute -inset-8 rounded-[2rem] bg-db-gold-500/10 blur-3xl"
              aria-hidden="true"
            />
            <div className="relative rounded-2xl border border-white/15 bg-black/55 px-7 py-8 shadow-[0_24px_80px_rgba(0,0,0,0.45)] backdrop-blur-xl md:px-8 md:py-9">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-db-gold-500">
                {t("auth.kicker")}
              </p>
              <h1
                className="mb-2 text-[1.85rem] leading-tight text-white"
                style={{ fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}
              >
                {t("auth.title")}
              </h1>
              <p className="mb-7 text-sm text-white/65">{t("auth.subtitle")}</p>

              {linkSent ? (
                <div className="flex flex-col gap-3" role="status">
                  <p className="text-sm text-white/90">{t("auth.checkInbox")}</p>
                  <p className="text-sm text-white/60">{t("auth.checkInboxHint", { email })}</p>
                  <button
                    type="button"
                    className="mt-2 text-sm text-db-gold-500 underline-offset-2 hover:underline"
                    onClick={() => {
                      setLinkSent(false)
                      setError(null)
                    }}
                  >
                    {t("auth.sendAgain")}
                  </button>
                </div>
              ) : (
                <form className="flex flex-col gap-4" onSubmit={onSubmit} aria-label={t("auth.formAria")}>
                  <label className="flex flex-col gap-1.5">
                    <span className="text-xs font-medium tracking-wide text-white/80">
                      {t("auth.emailLabel")}
                    </span>
                    <input
                      type="email"
                      name="email"
                      autoComplete="email"
                      autoFocus
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder={t("auth.emailPlaceholder")}
                      className="h-11 rounded-md border border-white/20 bg-black/45 px-3 text-sm text-white outline-none placeholder:text-white/35 focus:border-db-gold-500 focus:ring-1 focus:ring-db-gold-500/50"
                    />
                  </label>

                  {error || noModules || profileErrorMessage ? (
                    <p className="text-sm text-[#ffb4b4]" role="alert">
                      {error ?? profileErrorMessage ?? t("auth.noModules")}
                    </p>
                  ) : null}

                  <button
                    type="submit"
                    disabled={submitting}
                    className="mt-1 inline-flex h-11 items-center justify-center rounded-md bg-db-gold-500 px-4 text-sm font-medium text-db-navy-ink transition-colors hover:bg-db-gold-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {submitting ? t("auth.submittingLink") : t("auth.sendLink")}
                  </button>
                </form>
              )}
            </div>
          </div>
        </main>

        <p className="pb-6 text-center text-[11px] tracking-[0.12em] text-white/45">
          {t("auth.footer")}
        </p>
      </div>
    </div>
  )
}
