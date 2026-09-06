import type { ModuleManifest } from "@/modules/manifest"

export const rattsunderlagManifest: ModuleManifest = {
  id: "rattsunderlag",
  nameKey: "modules.rattsunderlag.name",
  icon: "⚖️",
  frontendEntry: "modules/rattsunderlag",
  homePath: "/rattsunderlag",
  components: [],
  reportModes: ["rattsunderlag"],
  navItems: [{ key: "nav.rattsunderlag", to: "/rattsunderlag", match: "/rattsunderlag" }],
}
