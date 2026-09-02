import type { MessageKey } from "@/i18n"
import { homePathForModules } from "@/lib/moduleHomePaths"
import type { ModuleManifest } from "@/modules/manifest"
import { moduleHasComponent } from "@/modules/manifest"
import { manifestsForIds } from "@/modules/moduleRegistry"

export type ShellNavItem = {
  key: MessageKey
  to: string
  match: string
  showActiveJobBadge?: boolean
}

export type ShellNavSection = {
  id: string
  titleKey?: MessageKey
  items: ShellNavItem[]
}

const NAV_MODULE_ORDER = ["politik", "dd", "expertgranskning"] as const

function sortManifestsForNav(manifests: ModuleManifest[]): ModuleManifest[] {
  return [...manifests].sort((a, b) => {
    const ai = NAV_MODULE_ORDER.indexOf(a.id as (typeof NAV_MODULE_ORDER)[number])
    const bi = NAV_MODULE_ORDER.indexOf(b.id as (typeof NAV_MODULE_ORDER)[number])
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
}

function moduleSectionItems(
  manifest: ModuleManifest,
  moduleIds: readonly string[],
): ShellNavItem[] {
  const bolagOnly = moduleIds.includes("dd") && !moduleIds.includes("politik")
  return manifest.navItems
    .filter((item) => item.component == null || moduleHasComponent(manifest, item.component))
    .map((item) => {
      if (manifest.id === "expertgranskning" && bolagOnly) {
        return {
          key: item.key,
          to: "/bolag/expertgranskning",
          match: "/bolag/expertgranskning",
        }
      }
      return { key: item.key, to: item.to, match: item.match }
    })
}

function sharedNavItems(moduleIds: readonly string[]): ShellNavItem[] {
  const bolagOnly = moduleIds.includes("dd") && !moduleIds.includes("politik")
  const prefix = bolagOnly ? "/bolag" : ""
  return [
    { key: "nav.reports", to: `${prefix}/reports`, match: `${prefix}/reports` },
    { key: "nav.feedback", to: `${prefix}/feedback`, match: `${prefix}/feedback` },
    {
      key: "nav.jobs",
      to: `${prefix}/jobs`,
      match: `${prefix}/jobs`,
      showActiveJobBadge: true,
    },
  ]
}

function adminNavItems(): ShellNavItem[] {
  return [
    { key: "nav.tools", to: "/tools", match: "/tools" },
    { key: "nav.users", to: "/anvandare", match: "/anvandare" },
  ]
}

export function brandToForModules(moduleIds: readonly string[]): string {
  return homePathForModules(moduleIds) ?? "/"
}

export function buildSidebarNav(opts: {
  moduleIds: readonly string[]
  showTools: boolean
}): ShellNavSection[] {
  const moduleIds = [...opts.moduleIds]
  if (opts.showTools && !moduleIds.includes("expertgranskning")) {
    moduleIds.push("expertgranskning")
  }
  const sections: ShellNavSection[] = []
  for (const manifest of sortManifestsForNav(manifestsForIds(moduleIds))) {
    const items = moduleSectionItems(manifest, opts.moduleIds)
    if (items.length === 0) continue
    sections.push({ id: manifest.id, titleKey: manifest.nameKey, items })
  }
  sections.push({ id: "shared", items: sharedNavItems(opts.moduleIds) })
  if (opts.showTools) {
    sections.push({ id: "admin", items: adminNavItems() })
  }
  return sections
}
