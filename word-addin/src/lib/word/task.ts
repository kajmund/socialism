import type { WordTask, WordTaskScope } from "@/lib/types"

export function createWordTask(args: {
  panelId: number
  scope: WordTaskScope
}): WordTask {
  return {
    task_type: "review",
    scope: args.scope,
    expert_strategy: { type: "panel", panel_id: args.panelId },
  }
}
