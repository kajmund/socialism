import { useEffect, useMemo, useState } from "react"
import { listPersonas, type LibraryPersona } from "@/api/personas"
import {
  reactPlaygroundImage,
  type PlaygroundImageReactResponse,
  type PlaygroundLocale,
} from "@/api/playground"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

function pct(rate: number): string {
  return String(Math.round(rate * 1000) / 10)
}

type SsrBlockProps = {
  title: string
  slice: PlaygroundImageReactResponse["ssr"]["tone"]
  predictedLabel: string
}

function SsrBlock({ title, slice, predictedLabel }: SsrBlockProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="text-sm text-muted-foreground">
        {predictedLabel}: {slice.predicted_label}
      </p>
      <ul className="grid gap-1 text-sm sm:grid-cols-2">
        {Object.entries(slice.shares).map(([lab, share]) => (
          <li
            key={lab}
            className="flex justify-between gap-4 border-b border-[color:var(--border-hairline)] py-1"
          >
            <span>{lab}</span>
            <span className="font-mono">{pct(share)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function PlaygroundImagePanel() {
  const { t } = useLocale()
  const [personas, setPersonas] = useState<LibraryPersona[]>([])
  const [loadingPersonas, setLoadingPersonas] = useState(true)
  const [personaId, setPersonaId] = useState("")
  const [anchorLocale, setAnchorLocale] = useState<PlaygroundLocale>("sv")
  const [temperature, setTemperature] = useState(0.1)
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PlaygroundImageReactResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoadingPersonas(true)
      try {
        const rows = await listPersonas()
        if (cancelled) return
        setPersonas(rows)
        if (rows[0]) setPersonaId(rows[0].id)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      } finally {
        if (!cancelled) setLoadingPersonas(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => {
      URL.revokeObjectURL(url)
    }
  }, [file])

  const selectedPersona = useMemo(
    () => personas.find((p) => p.id === personaId) ?? null,
    [personas, personaId],
  )

  async function onRun() {
    setError(null)
    if (!personaId) {
      setError(t("playground.image.noPersona"))
      return
    }
    if (!file) {
      setError(t("playground.image.noImage"))
      return
    }
    if (!Number.isFinite(temperature) || temperature <= 0) {
      setError(t("playground.temperatureInvalid"))
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      form.set("persona_id", personaId)
      form.set("locale", anchorLocale)
      form.set("temperature", String(temperature))
      form.set("image", file)
      const out = await reactPlaygroundImage(form)
      setResult(out)
    } catch (err) {
      setError(t("playground.error", { message: errorMessage(err) }))
    } finally {
      setBusy(false)
    }
  }

  if (loadingPersonas) {
    return <p className="text-sm text-muted-foreground">{t("playground.image.loadingPersonas")}</p>
  }

  return (
    <section
      id="playground-panel-image"
      role="tabpanel"
      aria-labelledby="playground-tab-image"
      className="space-y-6"
    >
      <p className="text-sm text-muted-foreground">{t("playground.image.intro")}</p>

      {personas.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("playground.image.noPersonas")}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex min-w-[220px] flex-col gap-1 text-sm">
              <span>{t("playground.image.persona")}</span>
              <select
                className="rounded border border-[color:var(--border-hairline)] bg-[color:var(--db-ink-0)] px-2 py-1.5"
                value={personaId}
                onChange={(e) => {
                  setPersonaId(e.target.value)
                  setResult(null)
                }}
              >
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[140px] flex-col gap-1 text-sm">
              <span>{t("playground.locale")}</span>
              <select
                className="rounded border border-[color:var(--border-hairline)] bg-[color:var(--db-ink-0)] px-2 py-1.5"
                value={anchorLocale}
                onChange={(e) => setAnchorLocale(e.target.value as PlaygroundLocale)}
              >
                <option value="sv">{t("playground.localeSv")}</option>
                <option value="en">{t("playground.localeEn")}</option>
              </select>
            </label>
            <label className="flex min-w-[120px] flex-col gap-1 text-sm">
              <span>{t("playground.temperature")}</span>
              <input
                type="number"
                step="0.05"
                min="0.01"
                className="rounded border border-[color:var(--border-hairline)] bg-[color:var(--db-ink-0)] px-2 py-1.5"
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
              />
            </label>
          </div>

          <div className="space-y-2">
            <label className="flex flex-col gap-1 text-sm">
              <span>{t("playground.image.upload")}</span>
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                className="text-sm"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null)
                  setResult(null)
                }}
              />
            </label>
            {previewUrl ? (
              <img
                src={previewUrl}
                alt={t("playground.image.previewAlt")}
                className="max-h-48 max-w-full rounded border border-[color:var(--border-hairline)] object-contain"
              />
            ) : null}
          </div>

          {selectedPersona ? (
            <p className="text-sm text-muted-foreground">
              {t("playground.image.selectedHint", { name: selectedPersona.name })}
            </p>
          ) : null}

          <Button type="button" disabled={busy} onClick={() => void onRun()}>
            {busy ? t("playground.running") : t("playground.image.run")}
          </Button>
        </>
      )}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {result ? (
        <div className="space-y-4 rounded border border-[color:var(--border-hairline)] p-4">
          <p className="text-sm text-muted-foreground">
            {t("playground.image.elapsed", { ms: String(result.elapsed_ms) })}
          </p>
          <div>
            <h2 className="mb-1 text-base font-medium">{t("playground.image.descriptionHeading")}</h2>
            <p className="text-sm">{result.image_description}</p>
          </div>
          <div>
            <h2 className="mb-1 text-base font-medium">{t("playground.image.reactionHeading")}</h2>
            <p className="text-sm">{result.reaction}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("playground.image.lexiconLabel", { label: result.lexicon_label })}
            </p>
          </div>
          <div className="grid gap-6 md:grid-cols-2">
            <SsrBlock
              title={t("playground.dimensionTone")}
              slice={result.ssr.tone}
              predictedLabel={t("playground.predicted")}
            />
            <SsrBlock
              title={t("playground.dimensionStyle")}
              slice={result.ssr.style}
              predictedLabel={t("playground.predicted")}
            />
          </div>
        </div>
      ) : null}
    </section>
  )
}
