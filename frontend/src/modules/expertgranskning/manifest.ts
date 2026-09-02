import type { ModuleManifest } from "@/modules/manifest"

export const expertgranskningManifest: ModuleManifest = {
  id: "expertgranskning",
  nameKey: "modules.expertgranskning.name",
  icon: "📝",
  frontendEntry: "expertgranskning",
  homePath: "/expertgranskning",
  components: ["panel_engine", "spindoctor"],
  reportModes: ["expertgranskning"],
}
