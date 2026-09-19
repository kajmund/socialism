import { useState } from "react"
import { deletePersonaAvatar, uploadPersonaAvatar } from "@/api/personas"
import { ProfileAvatar } from "@/components/profiles/ProfileAvatar"
import { useLocale } from "@/i18n"

type Props = {
  personaId: string
  path: string | null
  initials: string
  onChange: (path: string | null) => void
  onError?: () => void
}

export function PersonaAvatarPicker({
  personaId,
  path,
  initials,
  onChange,
  onError,
}: Props) {
  const { t } = useLocale()
  const [busy, setBusy] = useState(false)

  async function upload(file: File) {
    setBusy(true)
    try {
      const result = await uploadPersonaAvatar(personaId, file)
      onChange(result.avatar_url)
    } catch {
      onError?.()
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      await deletePersonaAvatar(personaId)
      onChange(null)
    } catch {
      onError?.()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="persona-avatar-picker relative shrink-0">
      <label
        className={`avatar grid place-items-center overflow-hidden${busy ? " opacity-60" : ""}`}
        title={t("experts.avatar.upload")}
      >
        {path ? (
          <ProfileAvatar path={path} className="size-full rounded-[inherit] object-cover" />
        ) : (
          initials
        )}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="sr-only"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
            event.target.value = ""
          }}
        />
      </label>
      {path ? (
        <button
          type="button"
          className="absolute -right-1 -top-1 grid size-5 place-items-center rounded-full border border-[color:var(--border-hairline)] bg-db-ink-0 text-[10px] leading-none text-[color:var(--text-muted)] hover:text-[color:var(--text-body)]"
          aria-label={t("experts.avatar.remove")}
          disabled={busy}
          onClick={() => void remove()}
        >
          ×
        </button>
      ) : null}
    </div>
  )
}
