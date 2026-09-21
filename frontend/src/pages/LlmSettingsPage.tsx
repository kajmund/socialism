import { useCallback, useEffect, useMemo, useState } from "react"
import {
  createLlmConfiguration,
  deleteLlmConfiguration,
  getLlmSettings,
  probeLlm,
  setDefaultLlmConfiguration,
  updateLlmConfiguration,
  type LlmActive,
  type LlmCatalogProfile,
  type LlmConfiguration,
  type LlmProbeResult,
  type LlmSettingsResponse,
} from "@/api/llmSettings"
import { LLM_CAPABILITIES_CHANGED_EVENT } from "@/components/chat/useLlmCapabilities"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Draft = {
  name: string
  profileId: string
  temperature: number
  topP: number
  maxTokens: number
  reasoningEffort: string
}

function draftFromProfile(profile: LlmCatalogProfile, name: string): Draft {
  const defaults = Object.fromEntries(profile.params.map((param) => [param.key, param.default]))
  return {
    name,
    profileId: profile.id,
    temperature: Number(defaults.temperature ?? 1),
    topP: Number(defaults.top_p ?? 1),
    maxTokens: Number(defaults.max_tokens ?? 8192),
    reasoningEffort: String(defaults.reasoning_effort ?? "medium"),
  }
}

function draftFromConfiguration(row: LlmConfiguration, catalog: LlmCatalogProfile[]): Draft {
  const profile = catalog.find((item) => item.id === row.profile_id) ?? catalog[0]
  const fallback = profile ? draftFromProfile(profile, row.name) : null
  return {
    name: row.name,
    profileId: row.profile_id,
    temperature: row.temperature ?? fallback?.temperature ?? 1,
    topP: row.top_p ?? fallback?.topP ?? 1,
    maxTokens: row.max_tokens ?? fallback?.maxTokens ?? 8192,
    reasoningEffort: row.reasoning_effort ?? fallback?.reasoningEffort ?? "medium",
  }
}

function draftFromActive(active: LlmActive, catalog: LlmCatalogProfile[], name: string): Draft {
  const profile = catalog.find((row) => row.id === active.profile_id) ?? catalog[0]
  const fallback = profile ? draftFromProfile(profile, name) : null
  return {
    name,
    profileId: active.profile_id,
    temperature: active.temperature ?? fallback?.temperature ?? 1,
    topP: active.top_p ?? fallback?.topP ?? 1,
    maxTokens: active.max_tokens ?? fallback?.maxTokens ?? 8192,
    reasoningEffort: active.reasoning_effort ?? fallback?.reasoningEffort ?? "medium",
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
  const [selectedId, setSelectedId] = useState<number | "new" | null>(null)
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
      setSelectedId((current) => {
        if (current === "new") return current
        if (current != null && next.configurations.some((row) => row.id === current)) {
          return current
        }
        return next.default_id ?? next.configurations[0]?.id ?? "new"
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.loadError"))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!data) return
    if (selectedId === "new") {
      const profile = data.catalog[0]
      setDraft(profile ? draftFromProfile(profile, "") : draftFromActive(data.active, data.catalog, ""))
      return
    }
    const row = data.configurations.find((item) => item.id === selectedId)
    if (row) {
      setDraft(draftFromConfiguration(row, data.catalog))
      return
    }
    if (data.configurations.length === 0) {
      setDraft(draftFromActive(data.active, data.catalog, t("tools.llm.defaultName")))
    }
  }, [data, selectedId, t])

  const selected = useMemo(() => {
    if (!data || !draft) return null
    return data.catalog.find((row) => row.id === draft.profileId) ?? null
  }, [data, draft])

  const selectedRow =
    data && typeof selectedId === "number"
      ? data.configurations.find((row) => row.id === selectedId) ?? null
      : null

  const missingKey = Boolean(data && selected && !data.credentials[selected.provider])

  async function persistDraft(makeDefault: boolean) {
    if (!draft || !selected || !data) return
    const name = draft.name.trim()
    if (!name) {
      setError(t("tools.llm.nameRequired"))
      return
    }
    setSaving(true)
    setError(null)
    setSaved(false)
    const body = {
      name,
      profile_id: draft.profileId,
      temperature: draft.temperature,
      top_p: draft.topP,
      max_tokens: draft.maxTokens,
      reasoning_effort: selected.params.some((param) => param.key === "reasoning_effort")
        ? draft.reasoningEffort
        : null,
    }
    try {
      let savedRow: LlmConfiguration
      if (selectedId === "new" || selectedId == null || !selectedRow) {
        savedRow = await createLlmConfiguration({ ...body, is_default: makeDefault })
      } else {
        savedRow = await updateLlmConfiguration(selectedRow.id, body)
        if (makeDefault && !savedRow.is_default) {
          savedRow = await setDefaultLlmConfiguration(savedRow.id)
        }
      }
      const next = await getLlmSettings()
      setData(next)
      setSelectedId(savedRow.id)
      setSaved(true)
      if (savedRow.is_default) {
        window.dispatchEvent(new Event(LLM_CAPABILITIES_CHANGED_EVENT))
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function onSetDefault() {
    if (typeof selectedId !== "number") return
    setSaving(true)
    setError(null)
    try {
      await setDefaultLlmConfiguration(selectedId)
      const next = await getLlmSettings()
      setData(next)
      setSaved(true)
      window.dispatchEvent(new Event(LLM_CAPABILITIES_CHANGED_EVENT))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function onDelete() {
    if (typeof selectedId !== "number" || !selectedRow) return
    setSaving(true)
    setError(null)
    try {
      await deleteLlmConfiguration(selectedId)
      const next = await getLlmSettings()
      setData(next)
      setSelectedId(next.default_id ?? next.configurations[0]?.id ?? "new")
      setSaved(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.llm.deleteError"))
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

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-medium">{t("tools.llm.listTitle")}</h3>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              setSelectedId("new")
              setSaved(false)
            }}
          >
            {t("tools.llm.new")}
          </Button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {data.configurations.map((row) => {
            const profile = data.catalog.find((item) => item.id === row.profile_id)
            const selectedRowId = selectedId === row.id
            return (
              <button
                key={row.id}
                type="button"
                className={`rounded border p-3 text-left text-sm ${
                  selectedRowId
                    ? "border-db-ink-950 bg-db-ink-50"
                    : "border-[color:var(--border-hairline)]"
                }`}
                onClick={() => {
                  setSelectedId(row.id)
                  setSaved(false)
                }}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">{row.name}</span>
                  {row.is_default ? (
                    <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
                      {t("tools.llm.defaultBadge")}
                    </span>
                  ) : null}
                </span>
                <span className="mt-1 block text-muted-foreground">
                  {profile?.label ?? row.profile_id} · {row.provider} · {row.model}
                </span>
              </button>
            )
          })}
          {selectedId === "new" ? (
            <div className="rounded border border-dashed border-db-ink-950 p-3 text-sm">
              <span className="font-medium">{t("tools.llm.newDraft")}</span>
            </div>
          ) : null}
        </div>
      </section>

      <label className="block text-sm">
        <span className="mb-1 block">{t("tools.llm.nameLabel")}</span>
        <input
          className="w-full max-w-md rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
          value={draft.name}
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
        />
      </label>

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
                  const next = draftFromProfile(profile, draft.name)
                  setDraft(next)
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

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={saving || missingKey}
          onClick={() => void persistDraft(false)}
        >
          {saving ? t("tools.llm.saving") : t("tools.llm.save")}
        </Button>
        {selectedRow && !selectedRow.is_default ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={saving || missingKey}
            onClick={() => void onSetDefault()}
          >
            {t("tools.llm.setDefault")}
          </Button>
        ) : null}
        {selectedRow && !selectedRow.is_default ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={saving}
            onClick={() => void onDelete()}
          >
            {t("tools.llm.delete")}
          </Button>
        ) : null}
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
