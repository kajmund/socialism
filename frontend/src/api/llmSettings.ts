import { api } from "@/lib/api"

export type LlmParamSpec = {
  key: string
  kind: "float" | "int" | "enum"
  default?: number | string | null
  minimum?: number
  maximum?: number
  choices?: string[]
}

export type LlmCatalogProfile = {
  id: string
  label: string
  provider: "cerebras" | "deepseek"
  model: string
  supports_vision?: boolean
  allowed_image_types?: string[]
  params: LlmParamSpec[]
}

export type LlmActive = {
  profile_id: string
  provider: string
  model: string
  temperature: number | null
  top_p: number | null
  max_tokens: number
  reasoning_effort: string | null
}

export type LlmConfiguration = {
  id: number
  name: string
  profile_id: string
  provider: string
  model: string
  temperature: number | null
  top_p: number | null
  max_tokens: number
  reasoning_effort: string | null
  is_default: boolean
  created_at: string
  updated_at: string
}

export type LlmSettingsResponse = {
  catalog: LlmCatalogProfile[]
  active: LlmActive
  credentials: { cerebras: boolean; deepseek: boolean }
  configurations: LlmConfiguration[]
  default_id: number | null
  assignments: Record<string, number>
}

export type LlmPutBody = {
  profile_id: string
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  reasoning_effort?: string | null
}

export type LlmConfigurationWrite = {
  name: string
  profile_id: string
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  reasoning_effort?: string | null
  is_default?: boolean
}

export type LlmProbeBody = {
  prompt: string
  system?: string | null
  profile_id?: string | null
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  reasoning_effort?: string | null
}

export type LlmProbeResult = {
  response: string
  provider: string
  model: string
  reasoning_effort: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  round_trip_ms: number
  time_to_first_token_ms: number | null
  completion_tokens_per_second: number | null
  finish_reason: string | null
}

export function getLlmSettings(): Promise<LlmSettingsResponse> {
  return api.get<LlmSettingsResponse>("/llm")
}

export function putLlmSettings(body: LlmPutBody): Promise<LlmActive> {
  return api.put<LlmActive>("/llm", body)
}

export function createLlmConfiguration(body: LlmConfigurationWrite): Promise<LlmConfiguration> {
  return api.post<LlmConfiguration>("/llm/configurations", body)
}

export function updateLlmConfiguration(
  id: number,
  body: Partial<LlmConfigurationWrite>,
): Promise<LlmConfiguration> {
  return api.patch<LlmConfiguration>(`/llm/configurations/${id}`, body)
}

export function setDefaultLlmConfiguration(id: number): Promise<LlmConfiguration> {
  return api.post<LlmConfiguration>(`/llm/configurations/${id}/default`, {})
}

export function deleteLlmConfiguration(id: number): Promise<void> {
  return api.delete(`/llm/configurations/${id}`)
}

export function assignPromptLlmConfiguration(
  promptKey: string,
  llmConfigurationId: number | null,
): Promise<LlmSettingsResponse> {
  return api.put<LlmSettingsResponse>(`/llm/prompt-fields/${encodeURIComponent(promptKey)}`, {
    llm_configuration_id: llmConfigurationId,
  })
}

export function probeLlm(body: LlmProbeBody): Promise<LlmProbeResult> {
  return api.post<LlmProbeResult>("/llm/probe", body)
}
