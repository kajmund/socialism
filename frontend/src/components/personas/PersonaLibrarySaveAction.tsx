import { useState } from "react"
import { updatePersona } from "@/api/personas"
import { AdminButton } from "@/components/ui/admin-button"
import type { PersonaOrigin } from "@/data/library-types"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type PersonaLibrarySaveActionProps = {
  personaId: string | null | undefined
  origin: PersonaOrigin | null | undefined
  onSaved?: (origin: PersonaOrigin) => void
  onToast?: (message: string) => void
  size?: "sm" | "default"
  className?: string
}

export function PersonaLibrarySaveAction({
  personaId,
  origin,
  onSaved,
  onToast,
  size = "sm",
  className,
}: PersonaLibrarySaveActionProps) {
  const { t } = useLocale()
  const [saving, setSaving] = useState(false)
  const [savedOrigin, setSavedOrigin] = useState<PersonaOrigin | null>(null)

  const effectiveOrigin = savedOrigin ?? origin

  if (!personaId) return null

  if (effectiveOrigin && effectiveOrigin !== "population") {
    return (
      <span
        className={
          className ??
          "inline-flex items-center rounded border border-[color:var(--border-hairline)] bg-db-ink-50 px-2 py-0.5 text-xs font-medium text-[color:var(--text-muted)]"
        }
      >
        {t("personas.librarySave.inLibrary")}
      </span>
    )
  }

  return (
    <AdminButton
      variant="secondary"
      size={size}
      className={className}
      disabled={saving}
      onClick={() => {
        setSaving(true)
        void updatePersona(personaId, { origin: "manuell" })
          .then((detail) => {
            setSavedOrigin(detail.origin)
            onSaved?.(detail.origin)
            onToast?.(t("personas.librarySave.savedToast", { name: detail.name }))
          })
          .catch((err: unknown) => {
            onToast?.(
              err instanceof ApiError ? err.message : t("personas.librarySave.error"),
            )
          })
          .finally(() => setSaving(false))
      }}
    >
      {saving ? t("personas.librarySave.saving") : t("personas.librarySave.button")}
    </AdminButton>
  )
}
