import { useEffect, useRef, useState } from "react"
import { listLiveModels, listLiveVoices, type LiveVoiceOption, type LiveVoiceProviderName } from "@/api/personas"
import { ApiError } from "@/lib/api"
import { useLocale } from "@/i18n"

export function ExpertLiveVoiceFields({
  provider,
  voice,
  model,
  correctionEnabled,
  correctionTimeout,
  onChange,
  onCorrectionChange,
}: {
  provider: LiveVoiceProviderName
  voice: string
  model: string
  correctionEnabled: boolean
  correctionTimeout: number
  onChange: (provider: LiveVoiceProviderName, voice: string, model: string) => void
  onCorrectionChange?: (enabled: boolean, timeout: number) => void
}) {
  const { t } = useLocale()
  const [voices, setVoices] = useState<LiveVoiceOption[]>([])
  const [models, setModels] = useState<LiveVoiceOption[]>([])
  const [loading, setLoading] = useState(true)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const voiceRef = useRef(voice)
  voiceRef.current = voice
  const modelRef = useRef(model)
  modelRef.current = model

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listLiveVoices(provider)
      .then((rows) => {
        if (cancelled) return
        setVoices(rows)
        if (rows.length > 0 && !rows.some((row) => row.id === voiceRef.current)) onChange(provider, rows[0].id, modelRef.current)
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

  useEffect(() => {
    if (provider !== "openai") {
      setModels([])
      return
    }
    let cancelled = false
    setModelsLoading(true)
    listLiveModels("openai")
      .then((rows) => {
        if (cancelled) return
        setModels(rows)
        if (rows.length > 0 && !rows.some((row) => row.id === modelRef.current)) onChange(provider, voiceRef.current, rows[0].id)
      })
      .catch(() => {
        if (cancelled) return
        setModels([])
        setError(t("experts.voice.error"))
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false)
      })
    return () => {
      cancelled = true
    }
    // The model list follows the openai provider. A missing model is replaced once that list arrives.
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
              if (next === "gemini" || next === "elevenlabs" || next === "openai" || next === "socialism") onChange(next, "", next === "openai" ? model : "")
            }}
          >
            <option value="gemini">{t("experts.voice.gemini")}</option>
            <option value="elevenlabs">{t("experts.voice.elevenlabs")}</option>
            <option value="openai">{t("experts.voice.openai")}</option>
            <option value="socialism">{t("experts.voice.socialism")}</option>
          </select>
        </label>
        {provider === "openai" ? (
          <label className="grid gap-1 text-xs text-muted-foreground">
            {t("experts.voice.model")}
            <select
              className="rounded border bg-white px-2 py-1.5 text-sm text-[color:var(--text-body)]"
              aria-label={t("experts.voice.model")}
              value={models.some((row) => row.id === model) ? model : ""}
              disabled={modelsLoading || models.length === 0}
              onChange={(event) => onChange(provider, voice, event.target.value)}
            >
              {models.length === 0 ? <option value="">{modelsLoading ? t("experts.voice.loading") : t("experts.voice.empty")}</option> : null}
              {models.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="grid gap-1 text-xs text-muted-foreground">
          {t("experts.voice.voice")}
          <select
            className="rounded border bg-white px-2 py-1.5 text-sm text-[color:var(--text-body)]"
            aria-label={t("experts.voice.voice")}
            value={voices.some((row) => row.id === voice) ? voice : ""}
            disabled={loading || voices.length === 0}
            onChange={(event) => onChange(provider, event.target.value, model)}
          >
            {voices.length === 0 ? <option value="">{loading ? t("experts.voice.loading") : t("experts.voice.empty")}</option> : null}
            {voices.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        {provider === "socialism" ? (
          <>
            <label className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={correctionEnabled}
                onChange={(event) => onCorrectionChange?.(event.target.checked, correctionTimeout)}
              />
              {t("experts.voice.correction")}
            </label>
            <label className="grid gap-1 text-xs text-muted-foreground">
              {t("experts.voice.correctionTimeout")}
              <input
                type="number"
                className="rounded border bg-white px-2 py-1.5 text-sm text-[color:var(--text-body)]"
                aria-label={t("experts.voice.correctionTimeout")}
                step={0.1}
                min={0.5}
                max={10}
                value={correctionTimeout}
                disabled={!correctionEnabled}
                onChange={(event) => {
                  const value = Number(event.target.value)
                  if (Number.isFinite(value)) onCorrectionChange?.(correctionEnabled, value)
                }}
              />
            </label>
          </>
        ) : null}
        {error ? <span className="text-xs text-destructive" role="alert">{error}</span> : null}
      </div>
    </>
  )
}
