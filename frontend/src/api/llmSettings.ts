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

export type LlmSettingsResponse = {
  catalog: LlmCatalogProfile[]
  active: LlmActive
  credentials: { cerebras: boolean; deepseek: boolean }
}

export type LlmPutBody = {
  profile_id: string
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  reasoning_effort?: string | null
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

export function probeLlm(body: LlmProbeBody): Promise<LlmProbeResult> {
  return api.post<LlmProbeResult>("/llm/probe", body)
}
