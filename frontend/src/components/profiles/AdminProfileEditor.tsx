import { AdminButton } from "@/components/ui/admin-button"
import { useState } from "react"
import { api } from "@/lib/api"
import { useLocale } from "@/i18n"
import type { UserAccountRow } from "@/api/users"
import { ProfileForm } from "./ProfileForm"
import { AvatarEditor } from "./AvatarEditor"
export function AdminProfileEditor({ user, onSaved }: { user: UserAccountRow; onSaved: () => Promise<void> }) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  return <><AdminButton type="button" variant="secondary" onClick={() => setOpen(!open)}>{t("profile.edit")}</AdminButton>{open ? <div className="grid min-w-80 gap-4 py-4"><ProfileForm key={user.profile_revision} values={user} onSave={async (changes) => { await api.patch(`/users/${user.id}`, changes); await onSaved() }} /><AvatarEditor userId={user.id} path={user.avatar_url} onSaved={onSaved} /></div> : null}</>
}
