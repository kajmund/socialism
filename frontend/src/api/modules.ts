import { api } from "@/lib/api"

export type ProductModule = {
  id: string
  name: string
  icon: string
  prompt_namespace: string
  frontend_entry: string
  components: string[]
  report_modes: string[]
  has_sub_questions: boolean
  has_expert_defaults: boolean
  has_prompt_defaults: boolean
  supports_interview: boolean
}

export function listModules(): Promise<ProductModule[]> {
  return api.get<ProductModule[]>("/modules")
}
