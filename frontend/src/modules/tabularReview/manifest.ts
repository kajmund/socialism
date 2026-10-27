import type { ModuleManifest } from "@/modules/manifest"

export const tabularReviewManifest: ModuleManifest = {
  id: "tabular_review",
  nameKey: "modules.tabularReview.name",
  icon: "▦",
  frontendEntry: "modules/tabular_review",
  homePath: "/tabular-review",
  components: [],
  reportModes: [],
  navItems: [{ key: "nav.tabularReview", to: "/tabular-review", match: "/tabular-review" }],
}
