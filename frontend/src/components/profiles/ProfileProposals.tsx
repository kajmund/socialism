import { AdminButton } from "@/components/ui/admin-button"
import { useCallback, useEffect, useState } from "react"
import { type Proposal, profileFields, organizationFields } from "@/api/profiles"
import { api, ApiError } from "@/lib/api"
import { useLocale } from "@/i18n"
export function ProfileProposals({ onSaved, conversation, refreshKey = 0 }: { onSaved: () => Promise<void>; conversation?: string; refreshKey?: number }) {
  const { t } = useLocale()
  const [items, setItems] = useState<Proposal[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<"error" | "loadError" | "conflict" | null>(null)
  const reload = useCallback(async () => { const rows = await api.get<Proposal[]>("/me/profile-proposals"); setItems(conversation ? rows.filter((row) => row.conversation === conversation) : rows) }, [conversation])
  useEffect(() => { setItems([]); void reload().catch(() => setError("loadError")) }, [reload, refreshKey])
  async function decide(item: Proposal, decision: "approve" | "reject") {
    setBusy(item.id); setError(null)
    try {
      await api.post(`/me/profile-proposals/${item.id}/decision`, { conversation: item.conversation, decision })
      await reload(); await onSaved()
    } catch (err) { setError(err instanceof ApiError && err.status === 409 ? "conflict" : "error") } finally { setBusy(null) }
  }
  function label(key: string) {
    const field = [...profileFields, ...organizationFields].find((f) => f === key)
    return field ? t(`profile.${field}`) : key
  }
  return <section className="grid gap-3">
    {error ? <p role="alert">{t(`profile.${error}`)}</p> : null}
    {items.length ? <h2>{t("profile.pending")}</h2> : null}
    {items.map((item) => <article key={item.id} className="grid gap-3 rounded-md border border-[color:var(--border-hairline)] p-4">
      <h3>{item.target_label} · {item.target === "customer" ? t("profile.organization") : t("profile.title")}</h3>
      <p>{t("profile.proposalInfo")}</p>
      <dl>{Object.entries(item.changes).map(([key, value]) => <div key={key} className="mb-3"><dt className="font-medium">{label(key)}</dt><dd>{t("profile.before")}: {item.previous[key] || t("profile.empty")}</dd><dd>{t("profile.after")}: {value || t("profile.empty")}</dd></div>)}</dl>
      <div className="flex gap-2"><AdminButton variant="accent" disabled={busy !== null} onClick={() => void decide(item, "approve")}>{t("profile.approve")}</AdminButton><AdminButton variant="secondary" disabled={busy !== null} onClick={() => void decide(item, "reject")}>{t("profile.reject")}</AdminButton></div>
    </article>)}
  </section>
}
