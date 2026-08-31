import { useEffect, useState, type FormEvent } from "react"
import { listKunder, type Kund } from "@/api/kunder"
import { inviteUser, listUsers, type UserAccountRow } from "@/api/users"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import type { Role } from "@/lib/auth"

export function AnvandarePage() {
  const { t, intl } = useLocale()
  const [users, setUsers] = useState<UserAccountRow[]>([])
  const [kunder, setKunder] = useState<Kund[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [email, setEmail] = useState("")
  const [role, setRole] = useState<Role>("user")
  const [kundId, setKundId] = useState<number | "">("")
  const [submitting, setSubmitting] = useState(false)

  async function reload() {
    const [userRows, kundRows] = await Promise.all([listUsers(), listKunder()])
    setUsers(userRows)
    setKunder(kundRows)
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    reload()
      .then(() => {
        if (!cancelled) setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("tools.users.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2400)
    return () => window.clearTimeout(timer)
  }, [toast])

  function roleLabel(value: Role): string {
    switch (value) {
      case "admin":
        return t("auth.roleAdmin")
      case "user":
        return t("auth.roleUser")
      case "bolag":
        return t("auth.roleBolag")
      default: {
        const _exhaustive: never = value
        return _exhaustive
      }
    }
  }

  function formatDate(iso: string): string {
    return new Intl.DateTimeFormat(intl, {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date(iso))
  }

  async function onInvite(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const body =
        role === "admin"
          ? { email: email.trim(), role, kund_id: null }
          : { email: email.trim(), role, kund_id: Number(kundId) }
      await inviteUser(body)
      await reload()
      setInviteOpen(false)
      setEmail("")
      setRole("user")
      setKundId("")
      setToast(t("tools.users.inviteSent"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("tools.users.inviteError"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="muted max-w-2xl">{t("tools.users.intro")}</p>
        <button
          type="button"
          className="inline-flex h-9 items-center rounded-md bg-db-gold-500 px-3 text-sm font-medium text-db-navy-ink hover:bg-db-gold-700"
          onClick={() => {
            setInviteOpen(true)
            setError(null)
          }}
        >
          {t("tools.users.invite")}
        </button>
      </div>

      {toast ? <p className="text-sm text-muted-foreground">{toast}</p> : null}
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p className="muted">{t("tools.users.loading")}</p> : null}
      {!loading && users.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("tools.users.empty")}</p>
      ) : null}

      {!loading && users.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[color:var(--border-hairline)]">
                <th className="px-2 py-1.5 font-medium">{t("tools.users.colEmail")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.users.colRole")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.users.colKund")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.users.colInvited")}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((row) => (
                <tr key={row.id} className="border-b border-[color:var(--border-hairline)]">
                  <td className="px-2 py-2">{row.email}</td>
                  <td className="px-2 py-2">{roleLabel(row.role)}</td>
                  <td className="px-2 py-2">
                    {row.kund_name ?? t("tools.users.noKund")}
                  </td>
                  <td className="px-2 py-2">{formatDate(row.invited_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {inviteOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="invite-user-title"
        >
          <div className="w-full max-w-md rounded-lg border border-[color:var(--border-hairline)] bg-[color:var(--surface-card)] p-5 shadow-lg">
            <h2 id="invite-user-title" className="mb-4 text-lg font-medium">
              {t("tools.users.inviteTitle")}
            </h2>
            <form className="flex flex-col gap-3" onSubmit={onInvite}>
              <label className="flex flex-col gap-1 text-sm">
                <span>{t("tools.users.emailLabel")}</span>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-10 rounded-md border border-[color:var(--border-hairline)] bg-transparent px-3"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span>{t("tools.users.roleLabel")}</span>
                <select
                  value={role}
                  onChange={(e) => {
                    const next = e.target.value as Role
                    setRole(next)
                    if (next === "admin") setKundId("")
                  }}
                  className="h-10 rounded-md border border-[color:var(--border-hairline)] bg-transparent px-3"
                >
                  <option value="admin">{roleLabel("admin")}</option>
                  <option value="user">{roleLabel("user")}</option>
                  <option value="bolag">{roleLabel("bolag")}</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span>{t("tools.users.kundLabel")}</span>
                <select
                  value={kundId === "" ? "" : String(kundId)}
                  disabled={role === "admin"}
                  required={role !== "admin"}
                  onChange={(e) =>
                    setKundId(e.target.value === "" ? "" : Number(e.target.value))
                  }
                  className="h-10 rounded-md border border-[color:var(--border-hairline)] bg-transparent px-3 disabled:opacity-50"
                >
                  <option value="">{t("tools.users.kundPlaceholder")}</option>
                  {kunder.map((kund) => (
                    <option key={kund.id} value={kund.id}>
                      {kund.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-2 flex justify-end gap-2">
                <button
                  type="button"
                  className="h-9 rounded-md px-3 text-sm"
                  onClick={() => setInviteOpen(false)}
                  disabled={submitting}
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={submitting || (role !== "admin" && kundId === "")}
                  className="h-9 rounded-md bg-db-gold-500 px-3 text-sm font-medium text-db-navy-ink hover:bg-db-gold-700 disabled:opacity-50"
                >
                  {submitting ? t("tools.users.inviting") : t("tools.users.inviteSubmit")}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}
