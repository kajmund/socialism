import type { ModuleManifest } from "@/modules/manifest"

export const ddManifest: ModuleManifest = {
  id: "dd",
  nameKey: "modules.dd.name",
  icon: "🔍",
  frontendEntry: "dd",
  homePath: "/bolag",
  components: ["personas", "panel_engine", "spindoctor", "campaigns"],
}
