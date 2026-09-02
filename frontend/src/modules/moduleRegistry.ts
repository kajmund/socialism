import { ddManifest } from "@/modules/dd/manifest"
import { expertgranskningManifest } from "@/modules/expertgranskning/manifest"
import {
  moduleHasComponent,
  type ModuleComponentId,
  type ModuleManifest,
} from "@/modules/manifest"
import { politikManifest } from "@/modules/politik/manifest"

export const MODULE_REGISTRY: Record<string, ModuleManifest> = {
  dd: ddManifest,
  politik: politikManifest,
  expertgranskning: expertgranskningManifest,
}

export const MODULE_IDS = Object.keys(MODULE_REGISTRY)

export function getModule(id: string): ModuleManifest | undefined {
  return MODULE_REGISTRY[id]
}

export function manifestsForIds(ids: readonly string[]): ModuleManifest[] {
  const out: ModuleManifest[] = []
  const seen = new Set<string>()
  for (const id of ids) {
    if (seen.has(id)) continue
    const manifest = MODULE_REGISTRY[id]
    if (!manifest) continue
    seen.add(id)
    out.push(manifest)
  }
  return out
}

export function modulesWith(
  component: ModuleComponentId,
  ids?: readonly string[],
): ModuleManifest[] {
  const source = ids ? manifestsForIds(ids) : Object.values(MODULE_REGISTRY)
  return source.filter((manifest) => moduleHasComponent(manifest, component))
}

export function primaryCampaignModuleId(ids?: readonly string[]): string | null {
  return modulesWith("campaigns", ids)[0]?.id ?? null
}
