import type { MessageKey } from "@/i18n"

export const MODULE_COMPONENT_IDS = [
  "personas",
  "interview",
  "panel_engine",
  "spindoctor",
  "campaigns",
] as const

export type ModuleComponentId = (typeof MODULE_COMPONENT_IDS)[number]

export type ModuleManifest = {
  id: string
  nameKey: MessageKey
  icon: string
  frontendEntry: string
  homePath: string
  components: readonly ModuleComponentId[]
}

export function moduleHasComponent(
  manifest: ModuleManifest,
  component: ModuleComponentId,
): boolean {
  return manifest.components.includes(component)
}
