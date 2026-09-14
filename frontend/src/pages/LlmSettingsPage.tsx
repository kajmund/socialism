import { useCallback, useEffect, useMemo, useState } from "react"
import {
  getLlmSettings,
  probeLlm,
  putLlmSettings,
  type LlmActive,
  type LlmCatalogProfile,
  type LlmProbeResult,
  type LlmSettingsResponse,
} from "@/api/llmSettings"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Draft = {
  profileId: string
  temperature: number
  topP: number
  maxTokens: number
  reasoningEffort: string
}

function draftFromActive(active: LlmActive, catalog: LlmCatalogProfile[]): Draft {
  const profile = catalog.find((row) => row.id === active.profile_id) ?? catalog[0]
  const defaults = Object.fromEntries(
    (profile?.params ?? []).map((param) => [param.key, param.default]),
  )
  return {
    profileId: active.profile_id,
    temperature: active.temperature ?? Number(defaults.temperature ?? 1),
    topP: active.top_p ?? Number(defaults.top_p ?? 1),
    maxTokens: active.max_tokens ?? Number(defaults.max_tokens ?? 8192),
    reasoningEffort: active.reasoning_effort ?? String(defaults.reasoning_effort ?? "medium"),
  }
}

export function LlmSettingsPage() {
  const { t, intl } = useLocale()
  const numberFmt = useMemo(
    () => new Intl.NumberFormat(intl, { maximumFractionDigits: 1 }),
    [intl],
  )
  const intFmt = useMemo(() => new Intl.NumberFormat(intl), [intl])

  const [data, setData] = useState<LlmSettingsResponse | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [probing, setProbing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [systemPrompt, setSystemPrompt] = useState("")
  const [prompt, setPrompt] = useState("")
  const [probeResult, setProbeResult] = useState<LlmProbeResult | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await getLlmSettings()
      setData(next)
      setDraft(draftFromActive(next.active, next.catalog))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.loadError"))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void load()
  }, [load])

  const selected = useMemo(() => {
    if (!data || !draft) return null
    return data.catalog.find((row) => row.id === draft.profileId) ?? null
  }, [data, draft])

  const missingKey = Boolean(
    data && selected && !data.credentials[selected.provider],
  )

  async function onSave() {
    if (!draft || !selected || !data) return
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const body = {
        profile_id: draft.profileId,
        temperature: draft.temperature,
        top_p: draft.topP,
        max_tokens: draft.maxTokens,
        reasoning_effort: selected.params.some((param) => param.key === "reasoning_effort")
          ? draft.reasoningEffort
          : null,
      }
      const active = await putLlmSettings(body)
      setData({ ...data, active })
      setDraft(draftFromActive(active, data.catalog))
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function onProbe() {
    if (!draft || !selected) return
    if (!prompt.trim()) {
      setError(t("tools.llm.probeNeedPrompt"))
      return
    }
    setProbing(true)
    setError(null)
    setProbeResult(null)
    try {
      const result = await probeLlm({
        prompt: prompt.trim(),
        system: systemPrompt.trim() || null,
        profile_id: draft.profileId,
        temperature: draft.temperature,
        top_p: draft.topP,
        max_tokens: draft.maxTokens,
        reasoning_effort: selected.params.some((param) => param.key === "reasoning_effort")
          ? draft.reasoningEffort
          : null,
      })
      setProbeResult(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.probeError"))
    } finally {
      setProbing(false)
    }
  }

  function formatMs(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return t("common.emDash")
    return `${intFmt.format(Math.round(value))} ms`
  }

  function formatTps(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return t("common.emDash")
    return numberFmt.format(value)
  }

  if (loading && !data) {
    return <p className="text-sm text-muted-foreground">{t("tools.llm.loading")}</p>
  }

  if (!data || !draft || !selected) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-destructive">{error ?? t("tools.llm.loadError")}</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          {t("tools.cache.refresh")}
        </Button>
      </div>
    )
  }

  const activeProfile = data.catalog.find((row) => row.id === data.active.profile_id)
  const effortChoices =
    selected.params.find((param) => param.key === "reasoning_effort")?.choices ?? []
  const maxTokensSpec = selected.params.find((param) => param.key === "max_tokens")
  const maxTokensCeiling = maxTokensSpec?.maximum ?? 8192
  const maxTokensFloor = maxTokensSpec?.minimum ?? 1

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-medium">{t("tools.llm.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("tools.llm.intro")}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("tools.llm.activeLabel", {
            label: activeProfile?.label ?? data.active.profile_id,
            provider: data.active.provider,
            model: data.active.model,
          })}
        </p>
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {saved ? <p className="text-sm text-muted-foreground">{t("tools.llm.saveOk")}</p> : null}
      {missingKey ? (
        <p className="text-sm text-destructive">
          {t("tools.llm.missingKey", { provider: selected.provider })}
        </p>
      ) : null}

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">{t("tools.llm.profileLabel")}</legend>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {data.catalog.map((profile) => (
            <label
              key={profile.id}
              className="flex cursor-pointer items-start gap-2 rounded border border-[color:var(--border-hairline)] p-3 text-sm"
            >
              <input
                type="radio"
                name="llm-profile"
                className="mt-1"
                checked={draft.profileId === profile.id}
                onChange={() => {
                  const defaults = Object.fromEntries(
                    profile.params.map((param) => [param.key, param.default]),
                  )
                  setDraft({
                    profileId: profile.id,
                    temperature: Number(defaults.temperature ?? 1),
                    topP: Number(defaults.top_p ?? 1),
                    maxTokens: Number(defaults.max_tokens ?? 8192),
                    reasoningEffort: String(defaults.reasoning_effort ?? "medium"),
                  })
                  setSaved(false)
                }}
              />
              <span>
                <span className="block font-medium">{profile.label}</span>
                <span className="text-muted-foreground">
                  {profile.provider} · {profile.model}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-sm">
          <span className="mb-1 block">{t("tools.llm.temperature")}</span>
          <input
            type="number"
            step="0.1"
            min={0}
            max={2}
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={draft.temperature}
            onChange={(event) =>
              setDraft({ ...draft, temperature: Number(event.target.value) })
            }
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block">{t("tools.llm.topP")}</span>
          <input
            type="number"
            step="0.05"
            min={0.01}
            max={1}
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={draft.topP}
            onChange={(event) => setDraft({ ...draft, topP: Number(event.target.value) })}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block">{t("tools.llm.maxTokens")}</span>
          <input
            type="number"
            step="1"
            min={maxTokensFloor}
            max={maxTokensCeiling}
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={draft.maxTokens}
            onChange={(event) =>
              setDraft({ ...draft, maxTokens: Number(event.target.value) })
            }
          />
        </label>
        {effortChoices.length > 0 ? (
          <label className="block text-sm">
            <span className="mb-1 block">{t("tools.llm.reasoningEffort")}</span>
            <select
              className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
              value={draft.reasoningEffort}
              onChange={(event) =>
                setDraft({ ...draft, reasoningEffort: event.target.value })
              }
            >
              {effortChoices.map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <div>
        <Button
          type="button"
          size="sm"
          disabled={saving || missingKey}
          onClick={() => void onSave()}
        >
          {saving ? t("tools.llm.saving") : t("tools.llm.save")}
        </Button>
      </div>

      <section className="space-y-3 border-t border-[color:var(--border-hairline)] pt-6">
        <h3 className="text-base font-medium">{t("tools.llm.probeTitle")}</h3>
        <p className="text-sm text-muted-foreground">{t("tools.llm.probeIntro")}</p>
        <label className="block text-sm">
          <span className="mb-1 block">{t("tools.llm.probeSystem")}</span>
          <textarea
            rows={2}
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block">{t("tools.llm.probePrompt")}</span>
          <textarea
            rows={4}
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>
        <Button
          type="button"
          size="sm"
          disabled={probing || missingKey}
          onClick={() => void onProbe()}
        >
          {probing ? t("tools.llm.probeRunning") : t("tools.llm.probeRun")}
        </Button>

        {probeResult ? (
          <div className="space-y-4">
            <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <div className="text-muted-foreground">{t("tools.llm.statsRoundTrip")}</div>
                <div>{formatMs(probeResult.round_trip_ms)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">{t("tools.llm.statsTtft")}</div>
                <div>{formatMs(probeResult.time_to_first_token_ms)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">{t("tools.llm.statsTokPerSec")}</div>
                <div>{formatTps(probeResult.completion_tokens_per_second)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">{t("tools.llm.statsFinish")}</div>
                <div>{probeResult.finish_reason ?? t("common.emDash")}</div>
              </div>
              <div>
                <div className="text-muted-foreground">{t("tools.llm.statsPromptTokens")}</div>
                <div>{intFmt.format(probeResult.prompt_tokens)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">
                  {t("tools.llm.statsCompletionTokens")}
                </div>
                <div>{intFmt.format(probeResult.completion_tokens)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">{t("tools.llm.statsTotalTokens")}</div>
                <div>{intFmt.format(probeResult.total_tokens)}</div>
              </div>
            </div>
            <div>
              <h4 className="mb-1 text-sm font-medium">{t("tools.llm.responseTitle")}</h4>
              <pre className="whitespace-pre-wrap rounded border border-[color:var(--border-hairline)] p-3 text-sm">
                {probeResult.response}
              </pre>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  )
}
