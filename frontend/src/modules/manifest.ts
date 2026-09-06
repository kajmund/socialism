import type { MessageKey } from "@/i18n"

export const MODULE_COMPONENT_IDS = [
  "personas",
  "interview",
  "panel_engine",
  "spindoctor",
  "campaigns",
] as const

export type ModuleComponentId = (typeof MODULE_COMPONENT_IDS)[number]

export type ModuleNavItem = {
  key: MessageKey
  to: string
  match: string
  component?: ModuleComponentId
  /** When set, these items render under this sidenav heading instead of the module name. */
  sectionKey?: MessageKey
  /** Place the section immediately above reports / feedback / jobs. */
  beforeShared?: boolean
}

export type ModuleManifest = {
  id: string
  nameKey: MessageKey
  icon: string
  frontendEntry: string
  homePath: string
  components: readonly ModuleComponentId[]
  reportModes: readonly string[]
  navItems: readonly ModuleNavItem[]
}

export function moduleHasComponent(
  manifest: ModuleManifest,
  component: ModuleComponentId,
): boolean {
  return manifest.components.includes(component)
}
