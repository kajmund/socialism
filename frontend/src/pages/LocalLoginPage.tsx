import { useEffect, useState } from "react"
import { Link, Navigate } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { AuthSplash } from "@/auth/RequireAuth"
import { ApiError, api } from "@/lib/api"
import { authAdapter, homePathForUser } from "@/lib/auth"
import { useLocale } from "@/i18n"

type LocalLoginResponse = {
  access_token: string
  email: string
}

export function LocalLoginPage() {
  const { t } = useLocale()
  const { session, loading, resolvedModules, profileError } = useAuth()
  const [requestError, setRequestError] = useState<string | null>(null)
  const [started, setStarted] = useState(false)

  useEffect(() => {
    if (loading || session || started) return
    setStarted(true)
    void (async () => {
      try {
        const result = await api.post<LocalLoginResponse>("/auth/local-login")
        authAdapter.installLocalSession(result.access_token, result.email)
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
          setRequestError(t("auth.localLoginDisabled"))
          return
        }
        setRequestError(t("auth.localLoginFailed"))
      }
    })()
  }, [loading, session, started, t])

  if (session && resolvedModules.length > 0) {
    return <Navigate to={homePathForUser(resolvedModules)} replace />
  }

  if (loading || (!requestError && !profileError)) {
    return <AuthSplash />
  }

  const message =
    requestError ??
    (profileError === "not_provisioned"
      ? t("auth.notProvisioned")
      : profileError === "invalid_token"
        ? t("auth.invalidToken")
        : t("auth.profileFailed"))

  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-db-black px-4 text-white">
      <p className="mb-3 text-sm text-[#ffb4b4]" role="alert">
        {message}
      </p>
      <Link className="text-sm text-db-gold-500 underline-offset-2 hover:underline" to="/login">
        {t("auth.localLoginBack")}
      </Link>
    </div>
  )
}
