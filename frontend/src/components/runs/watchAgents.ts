import type { PopulationMember } from "@/data/library-types"
import type { BranchState, Injection, Tick } from "@/data/runs-types"
import type { RunWatchAgent } from "@/data/runWatch-types"

const TYPE_DEFAULT_NAME: Record<Injection["type"], string> = {
  party_post: "Partikonto",
  news_post: "Nyhetskonto",
  ad_post: "Annonskonto",
}

function injectorKey(injection: Injection): string {
  const sender = injection.sender.trim().replace(/^@/, "").toLocaleLowerCase("sv-SE")
  if (sender) return `${injection.type}:${sender}`
  return `${injection.type}:default`
}

function injectionHasContent(injection: Injection): boolean {
  if (injection.mode === "link" && injection.url.trim()) return true
  return Boolean(injection.text.trim())
}

function injectorDisplayName(injection: Injection): string {
  const raw = injection.sender.trim().replace(/^@/, "")
  return raw || TYPE_DEFAULT_NAME[injection.type]
}

export function ticksForVariant(
  variantId: string,
  mainTicks: Tick[],
  branch: BranchState | null,
): Tick[] {
  if (!branch) return mainTicks
  const stem = mainTicks.slice(0, Math.max(0, branch.afterIndex + 1))
  if (variantId === "a") return [...stem, ...branch.a]
  if (variantId === "b") return [...stem, ...branch.b]
  return mainTicks
}

/** Same OASIS index order as backend watch_agent_roster: injectors first. */
export function watchAgentsFromPopulation(
  members: PopulationMember[],
  ticks: Tick[],
): RunWatchAgent[] {
  const injectors: RunWatchAgent[] = []
  const seen = new Set<string>()
  for (const tick of ticks) {
    if (tick.silent) continue
    for (const injection of tick.injections) {
      if (!injectionHasContent(injection)) continue
      const key = injectorKey(injection)
      if (seen.has(key)) continue
      seen.add(key)
      injectors.push({
        index: injectors.length,
        username: "",
        member_name: injectorDisplayName(injection),
        persona_id: null,
        role: "injector",
      })
    }
  }
  const start = injectors.length
  const population = members.map((member, i) => ({
    index: start + i,
    username: "",
    member_name: member.name,
    persona_id: typeof member.id === "string" && member.id ? member.id : null,
    role: "population",
  }))
  return [...injectors, ...population]
}

export function mergeWatchAgents(
  fromPopulation: RunWatchAgent[],
  fromSocket: RunWatchAgent[],
): RunWatchAgent[] {
  const byIndex = new Map<number, RunWatchAgent>()
  for (const agent of fromPopulation) byIndex.set(agent.index, agent)
  for (const agent of fromSocket) {
    if (agent.member_name.trim()) byIndex.set(agent.index, agent)
  }
  return [...byIndex.values()]
}
