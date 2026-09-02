import type { ModuleManifest } from "@/modules/manifest"

export const politikManifest: ModuleManifest = {
  id: "politik",
  nameKey: "modules.politik.name",
  icon: "🗳️",
  frontendEntry: "politik",
  homePath: "/",
  components: ["personas", "interview", "spindoctor"],
  reportModes: ["quick", "full"],
  navItems: [
    { key: "nav.personas", to: "/personas", match: "/personas" },
    { key: "nav.populations", to: "/populations", match: "/populations" },
    { key: "nav.messages", to: "/messages", match: "/messages" },
    { key: "nav.runs", to: "/runs", match: "/runs" },
  ],
}
