import { api } from "@/lib/api"

export type PlaygroundLocale = "sv" | "en"
export type PlaygroundDimension = "tone" | "style"

export type AnchorSet = {
  name: string
  version: string
  labels: string[]
  statements: string[]
}

export type AnchorsResponse = {
  version: string
  tone: Record<PlaygroundLocale, AnchorSet>
  style: Record<PlaygroundLocale, AnchorSet>
}

export type RateRequest = {
  texts: string[]
  dimension?: PlaygroundDimension
  locale?: PlaygroundLocale
  anchor_set_id?: number
  labels?: string[]
  statements?: string[]
  temperature?: number
  human_labels?: string[]
  clip_for_embed?: boolean
  use_config_temperature?: boolean
}

export type RatePerText = {
  text: string
  pmf: Record<string, number>
  predicted_label: string
}

export type RateResponse = {
  anchor_set_name: string
  anchor_set_version: string
  labels: string[]
  shares: Record<string, number>
  per_text: RatePerText[]
  human_labels?: string[]
  accuracy?: number
  confusion?: Record<string, Record<string, number>>
}

export type CompareRequest = {
  texts: string[]
  locale?: PlaygroundLocale
  labels?: string[]
  statements?: string[]
  temperature?: number
}

export type CompareRow = {
  text: string
  ssr_label: string
  ssr_bucket: string
  lexicon_label: string
  match: boolean
  pmf: Record<string, number>
}

export type CompareResponse = {
  anchor_set_name: string
  anchor_set_version: string
  labels: string[]
  ssr_shares: Record<string, number>
  lexicon_shares: Record<string, number>
  agreement_rate: number
  rows: CompareRow[]
}

export type PromptRunRequest = {
  configuration_id: number
  prompt_key: string
  prompt_override?: string | null
  variables?: Record<string, string>
  user_message?: string | null
}

export type PromptVariant = {
  id: "A" | "B"
  rendered_prompt: string
  response: string
}

export type PromptRunResponse = {
  configuration_id: number
  prompt_key: string
  variants: PromptVariant[]
}

export function getPlaygroundAnchors(): Promise<AnchorsResponse> {
  return api.get<AnchorsResponse>("/playground/anchors")
}

export function ratePlaygroundSsr(body: RateRequest): Promise<RateResponse> {
  return api.post<RateResponse>("/playground/ssr/rate", body)
}

export type SampleFromRunRequest = {
  run_id: number
  attempt_id: string
  variant_id?: string | null
  use_report_sampling?: boolean
}

export type SampleFromRunResponse = {
  texts: string[]
  likes: number[]
  user_ids: number[]
  sampling: Record<string, unknown>
  clipped_preview: string[]
  variant_id: string | null
  bundle_label: string
}

export function samplePlaygroundSsrFromRun(
  body: SampleFromRunRequest,
): Promise<SampleFromRunResponse> {
  return api.post<SampleFromRunResponse>("/playground/ssr/sample-from-run", body)
}

export function comparePlaygroundSsr(body: CompareRequest): Promise<CompareResponse> {
  return api.post<CompareResponse>("/playground/ssr/compare", body)
}

export function runPlaygroundPrompt(body: PromptRunRequest): Promise<PromptRunResponse> {
  return api.post<PromptRunResponse>("/playground/prompts/run", body)
}

export type ToolFamilyId = "web_search" | "sympy"

export type ToolCatalogTool = {
  name: string
  family: ToolFamilyId
  description: string
  parameters: {
    type?: string
    properties?: Record<string, { type?: string; description?: string }>
    required?: string[]
  }
}

export type ToolCatalogFamily = {
  id: ToolFamilyId
  label: string
  tools: ToolCatalogTool[]
  unavailable_reason?: string | null
}

export type ToolCatalogResponse = {
  families: ToolCatalogFamily[]
}

export type ToolRunRequest = {
  tool_name: string
  arguments?: Record<string, unknown>
}

export type ToolRunResponse = {
  tool_name: string
  arguments: Record<string, unknown>
  result: unknown
  error: string | null
  elapsed_ms: number
}

export function getPlaygroundToolsCatalog(): Promise<ToolCatalogResponse> {
  return api.get<ToolCatalogResponse>("/playground/tools/catalog")
}

export function runPlaygroundTool(body: ToolRunRequest): Promise<ToolRunResponse> {
  return api.post<ToolRunResponse>("/playground/tools/run", body)
}

export type PlaygroundImageSsrSlice = {
  anchor_set_name: string
  anchor_set_version: string
  labels: string[]
  shares: Record<string, number>
  predicted_label: string
  pmf: Record<string, number>
}

export type PlaygroundImageModelOption = {
  id: string
  label: string
}

export type PlaygroundVisionProvider = {
  id: "openai" | "google" | "ollama"
  label: string
  available: boolean
  unavailable_reason: string | null
  models: PlaygroundImageModelOption[]
}

export type PlaygroundImageModelsResponse = {
  defaults: {
    vision_provider: PlaygroundVisionProvider["id"]
    vision_model: string
    reaction_model: string
  }
  vision_providers: PlaygroundVisionProvider[]
  reaction_models: PlaygroundImageModelOption[]
}

export type PlaygroundImageReactResponse = {
  persona_id: string
  persona_name: string
  image_description: string
  reaction: string
  lexicon_label: string
  locale: PlaygroundLocale
  temperature: number
  vision_provider: string
  vision_model: string
  reaction_model: string
  ssr: {
    tone: PlaygroundImageSsrSlice
    style: PlaygroundImageSsrSlice
  }
  elapsed_ms: number
}

export function getPlaygroundImageModels(): Promise<PlaygroundImageModelsResponse> {
  return api.get<PlaygroundImageModelsResponse>("/playground/image/models")
}

export function reactPlaygroundImage(
  form: FormData,
): Promise<PlaygroundImageReactResponse> {
  return api.postForm<PlaygroundImageReactResponse>("/playground/image/react", form, {
    timeoutMs: 120_000,
  })
}
