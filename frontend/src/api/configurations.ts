import type { CatalogItem, CatalogList } from "@/api/catalog"
import { api } from "@/lib/api"

export type ConfigurationLanguage = "sv" | "en" | "nb"

export type Configuration = {
  id: number
  name: string
  language: ConfigurationLanguage
  prompts: Record<string, string>
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ConfigurationWrite = {
  name: string
  language: ConfigurationLanguage
  prompts?: Record<string, string>
  is_active?: boolean
}

export type PromptField = {
  key: string
  section: string
  label: string
  hint: string
  default: string
}

export type PromptCatalog = {
  sections: { id: string; label: string }[]
  fields: PromptField[]
  defaults: Record<string, string>
}

export const CONFIGURATION_LANGUAGES: ConfigurationLanguage[] = ["sv", "en", "nb"]

export function listConfigurations(): Promise<Configuration[]> {
  return api.get<Configuration[]>("/configurations")
}

export function getConfiguration(id: number): Promise<Configuration> {
  return api.get<Configuration>(`/configurations/${id}`)
}

export function getPromptCatalog(params?: {
  language?: ConfigurationLanguage
  label_locale?: ConfigurationLanguage
}): Promise<PromptCatalog> {
  return api.get<PromptCatalog>("/configurations/catalog", params)
}

export function createConfiguration(body: ConfigurationWrite): Promise<Configuration> {
  return api.post<Configuration>("/configurations", body)
}

export function updateConfiguration(
  id: number,
  body: Partial<ConfigurationWrite>,
): Promise<Configuration> {
  return api.patch<Configuration>(`/configurations/${id}`, body)
}

export function activateConfiguration(id: number): Promise<Configuration> {
  return api.post<Configuration>(`/configurations/${id}/activate`, {})
}

export function deleteConfiguration(id: number): Promise<void> {
  return api.delete(`/configurations/${id}`)
}

export function listConfigurationCatalog(
  configurationId: number,
): Promise<CatalogList[]> {
  return api.get<CatalogList[]>(`/configurations/${configurationId}/catalog`)
}

export function updateConfigurationCatalogList(
  configurationId: number,
  key: string,
  items: CatalogItem[],
): Promise<CatalogList> {
  return api.put<CatalogList>(
    `/configurations/${configurationId}/catalog/${key}`,
    { items },
  )
}
