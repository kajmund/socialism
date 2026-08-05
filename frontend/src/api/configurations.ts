import { api } from "@/lib/api"

export type ConfigurationLanguage = "sv" | "en" | "nb"

export type Configuration = {
  id: number
  name: string
  language: ConfigurationLanguage
  prompt_text: string
  created_at: string
  updated_at: string
}

export type ConfigurationWrite = {
  name: string
  language: ConfigurationLanguage
  prompt_text: string
}

export const CONFIGURATION_LANGUAGES: ConfigurationLanguage[] = ["sv", "en", "nb"]

export function listConfigurations(): Promise<Configuration[]> {
  return api.get<Configuration[]>("/configurations")
}

export function getConfiguration(id: number): Promise<Configuration> {
  return api.get<Configuration>(`/configurations/${id}`)
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

export function deleteConfiguration(id: number): Promise<void> {
  return api.delete(`/configurations/${id}`)
}
