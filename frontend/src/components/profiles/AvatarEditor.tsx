import { AdminButton } from "@/components/ui/admin-button"
import { useState } from "react"
import { api } from "@/lib/api"
import { useLocale } from "@/i18n"
import { ProfileAvatar } from "./ProfileAvatar"
export function AvatarEditor({ userId, path, onSaved }: { userId: string; path: string | null; onSaved: () => Promise<void> }) {
  const { t } = useLocale()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  async function save(file?: File) {
    setBusy(true); setError(false)
    try {
      if (file) { const form = new FormData(); form.set("file", file); await api.postForm(`/profiles/${userId}/avatar`, form) }
      else await api.delete(`/profiles/${userId}/avatar`)
      await onSaved()
    } catch { setError(true) } finally { setBusy(false) }
  }
  return <div className="grid gap-2">
    <ProfileAvatar path={path} />
    <label className="grid gap-1 text-sm">{t("profile.upload")}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) void save(file); e.target.value = "" }} /></label>
    <p className="text-xs text-muted-foreground">{t("profile.imageHint")}</p>
    {path ? <AdminButton type="button" variant="secondary" className="justify-self-start" disabled={busy} onClick={() => void save()}>{t("profile.remove")}</AdminButton> : null}
    {error ? <p role="alert">{t("profile.error")}</p> : null}
  </div>
}
