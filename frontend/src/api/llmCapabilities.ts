import { api } from "@/lib/api"

export type LlmCapabilities = {
  supports_vision: boolean
  provider: string
  model: string
  profile_id: string
  allowed_image_types: string[]
}

export function getLlmCapabilities(): Promise<LlmCapabilities> {
  return api.get<LlmCapabilities>("/llm/capabilities")
}
