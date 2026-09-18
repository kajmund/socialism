import { Brain } from "lucide-react"
import { useState } from "react"
import {
  clearPersonaMemories,
  deletePersonaMemory,
  listPersonaMemories,
  updatePersonaMemory,
  type ExpertMemory,
} from "@/api/expertMemory"
import { ExpertMemoryDialog } from "@/components/experts/ExpertMemoryDialog"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function SmeExpertMemoryButton({
  personaId,
  name,
}: {
  personaId: string
  name: string
}) {
  const { intl, t } = useLocale()
  const [open, setOpen] = useState(false)
  const [memories, setMemories] = useState<ExpertMemory[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function openMemoryLog() {
    setOpen(true)
    setLoading(true)
    setError(null)
    try {
      const listed = await listPersonaMemories(personaId)
      setMemories(listed.memories)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("experts.memory.logError"),
      )
    } finally {
      setLoading(false)
    }
  }

  function formatWhen(iso: string): string {
    if (!iso) return ""
    const date = new Date(iso)
    if (Number.isNaN(date.getTime())) return iso
    return new Intl.DateTimeFormat(intl, {
      dateStyle: "short",
      timeStyle: "short",
    }).format(date)
  }

  return (
    <>
      <AdminButton
        variant="secondary"
        size="sm"
        className="gap-1.5"
        aria-label={t("experts.memory.logAria", { name })}
        onClick={() => void openMemoryLog()}
      >
        <Brain size={15} aria-hidden="true" />
        <span className="hidden sm:inline">{t("experts.memory.log")}</span>
      </AdminButton>
      <ExpertMemoryDialog
        open={open}
        name={name}
        memories={memories}
        loading={loading}
        error={error}
        formatWhen={formatWhen}
        onSave={async (row, text) => {
          const updated = await updatePersonaMemory(personaId, row.id, text)
          setMemories((current) =>
            current.map((item) => (item.id === row.id ? updated : item)),
          )
          return updated
        }}
        onDelete={async (row) => {
          await deletePersonaMemory(personaId, row.id)
          setMemories((current) =>
            current.filter((item) => item.id !== row.id),
          )
        }}
        onClearAll={async () => {
          await clearPersonaMemories(personaId)
          setMemories([])
        }}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
