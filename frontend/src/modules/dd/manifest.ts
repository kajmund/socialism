import type { ModuleManifest } from "@/modules/manifest"

export const ddManifest: ModuleManifest = {
  id: "dd",
  nameKey: "modules.dd.name",
  icon: "🔍",
  frontendEntry: "dd",
  homePath: "/bolag",
  components: ["personas", "panel_engine", "spindoctor", "campaigns"],
  reportModes: ["dd"],
  navItems: [
    {
      key: "bolag.nav.experter",
      to: "/bolag/experter",
      match: "/bolag/experter",
      component: "personas",
      sectionKey: "bolag.nav.experter",
      beforeShared: true,
    },
    {
      key: "bolag.nav.expertPanels",
      to: "/bolag/expertpaneler",
      match: "/bolag/expertpaneler",
      component: "panel_engine",
      sectionKey: "bolag.nav.experter",
      beforeShared: true,
    },
    { key: "bolag.nav.campaigns", to: "/bolag/campaigns", match: "/bolag/campaigns", component: "campaigns" },
  ],
}
