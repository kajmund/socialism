import { useEffect, useState } from "react"
import { getPersona, updatePersona } from "@/api/personas"
import { ExpertToolsFields } from "@/components/experts/ExpertToolsFields"
import {
  normalizeExpertTools,
  type ExpertToolId,
} from "@/data/expert-tools"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function SmeExpertToolsButton({
  personaId,
}: {
  personaId: string
}) {
  const { t } = useLocale()
  const [tools, setTools] = useState<ExpertToolId[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getPersona(personaId)
      .then((persona) => {
        if (!cancelled) setTools(normalizeExpertTools(persona.tools))
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : t("personas.composer.fetchPersonaError"),
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [personaId, t])

  function saveTools(next: ExpertToolId[]) {
    const previous = tools
    setTools(next)
    setSaving(true)
    setError(null)
    void updatePersona(personaId, { tools: next })
      .then((persona) => setTools(normalizeExpertTools(persona.tools)))
      .catch((err: unknown) => {
        setTools(previous)
        setError(
          err instanceof ApiError ? err.message : t("common.saveError"),
        )
      })
      .finally(() => setSaving(false))
  }

  return (
    <ExpertToolsFields
      tools={tools}
      onChange={saveTools}
      disabled={loading || saving}
      error={error}
    />
  )
}
