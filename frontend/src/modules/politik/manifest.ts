import type { ModuleManifest } from "@/modules/manifest"

export const politikManifest: ModuleManifest = {
  id: "politik",
  nameKey: "modules.politik.name",
  icon: "🗳️",
  frontendEntry: "politik",
  homePath: "/",
  components: ["personas", "interview", "spindoctor"],
  reportModes: ["quick", "full"],
}
