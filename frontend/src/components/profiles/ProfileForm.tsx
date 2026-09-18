import { AdminButton } from "@/components/ui/admin-button"
import { useState } from "react"
import { organizationFields, profileFields, type OrganizationField, type ProfileField } from "@/api/profiles"
import { useLocale } from "@/i18n"

type Field = ProfileField | OrganizationField
export function ProfileForm({ values, organization = false, onSave }: { values: Partial<Record<Field, string | null>>; organization?: boolean; onSave: (changes: Partial<Record<Field, string | null>>) => Promise<void> }) {
  const { t } = useLocale()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<"saved" | "error" | null>(null)
  const fields = organization ? organizationFields : profileFields
  return <form className="grid gap-3" onSubmit={async (event) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const changes = Object.fromEntries(fields.filter((key) => (String(data.get(key) ?? "").trim() || null) !== (values[key] || null)).map((key) => [key, String(data.get(key) ?? "").trim() || null]))
    setBusy(true); setStatus(null)
    try { await onSave(changes); setStatus("saved") } catch { setStatus("error") } finally { setBusy(false) }
  }}>
    <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
      {fields.map((key) => <label key={key} className="grid gap-1 text-sm">
        {t(`profile.${key}`)}
        <input name={key} defaultValue={values[key] ?? ""} maxLength={key === "country_code" ? 2 : key === "job_title" ? 200 : key === "postal_code" ? 32 : key === "organization_number" ? 40 : ["first_name", "last_name", "city"].includes(key) ? 100 : 255} className="rounded-md border border-[color:var(--border-hairline)] bg-transparent px-3 py-2" />
      </label>)}
    </fieldset>
    <AdminButton type="submit" disabled={busy} variant="accent" className="justify-self-start">{busy ? t("common.saving") : t("profile.save")}</AdminButton>
    {status ? <p role={status === "error" ? "alert" : "status"}>{t(`profile.${status}`)}</p> : null}
  </form>
}
