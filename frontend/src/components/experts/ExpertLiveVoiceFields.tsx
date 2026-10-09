import { useEffect, useRef, useState } from "react"
import { listLiveVoices, type LiveVoiceOption, type LiveVoiceProviderName } from "@/api/personas"
import { ApiError } from "@/lib/api"
import { useLocale } from "@/i18n"

export function ExpertLiveVoiceFields({
  provider,
  voice,
  onChange,
}: {
  provider: LiveVoiceProviderName
  voice: string
  onChange: (provider: LiveVoiceProviderName, voice: string) => void
}) {
  const { t } = useLocale()
  const [voices, setVoices] = useState<LiveVoiceOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const voiceRef = useRef(voice)
  voiceRef.current = voice

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listLiveVoices(provider)
      .then((rows) => {
        if (cancelled) return
        setVoices(rows)
        if (rows.length > 0 && !rows.some((row) => row.id === voiceRef.current)) onChange(provider, rows[0].id)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setVoices([])
        setError(err instanceof ApiError ? err.message : t("experts.voice.error"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // The voice list follows the provider. A missing voice is replaced once that list arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  return (
    <>
      <div className="layer-h">{t("experts.voice.heading")}</div>
      <div className="grid gap-2 px-3 pb-3">
        <label className="grid gap-1 text-xs text-muted-foreground">
          {t("experts.voice.provider")}
          <select
            className="rounded border bg-white px-2 py-1.5 text-sm text-[color:var(--text-body)]"
            aria-label={t("experts.voice.provider")}
            value={provider}
            onChange={(event) => {
              const next = event.target.value
              if (next === "gemini" || next === "elevenlabs" || next === "socialism") onChange(next, "")
            }}
          >
            <option value="gemini">{t("experts.voice.gemini")}</option>
            <option value="elevenlabs">{t("experts.voice.elevenlabs")}</option>
            <option value="socialism">{t("experts.voice.socialism")}</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          {t("experts.voice.voice")}
          <select
            className="rounded border bg-white px-2 py-1.5 text-sm text-[color:var(--text-body)]"
            aria-label={t("experts.voice.voice")}
            value={voices.some((row) => row.id === voice) ? voice : ""}
            disabled={loading || voices.length === 0}
            onChange={(event) => onChange(provider, event.target.value)}
          >
            {voices.length === 0 ? <option value="">{loading ? t("experts.voice.loading") : t("experts.voice.empty")}</option> : null}
            {voices.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        {error ? <span className="text-xs text-destructive" role="alert">{error}</span> : null}
      </div>
    </>
  )
}
