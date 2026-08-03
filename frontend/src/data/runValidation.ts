import type { BranchState, Injection, Tick } from "@/data/runs-types"

export type RunConfigValidation = {
  ok: boolean
  errors: string[]
}

function injectionHasContent(injection: Injection): boolean {
  if (injection.mode === "link" && injection.url.trim()) return true
  return Boolean(injection.text.trim())
}

function validateTick(tick: Tick, label: string, errors: string[]): void {
  if (tick.rounds < 1) {
    errors.push(`${label}: antal ronder måste vara minst 1`)
  }
  if (tick.silent) return
  const withContent = tick.injections.filter(injectionHasContent)
  if (withContent.length === 0) {
    errors.push(
      `${label}: lägg till minst ett budskap med text eller länk, eller markera dagen som tyst`,
    )
  }
}

/** Domain checks before start — not OASIS/API/engine plumbing. */
export function validateRunConfig(input: {
  name: string
  populationId: number | null
  populationSize: number
  seed: string
  startDate: string
  mainTicks: Tick[]
  branch: BranchState | null
}): RunConfigValidation {
  const errors: string[] = []

  if (!input.name.trim()) {
    errors.push("Ge körningen ett namn")
  }
  if (input.populationId == null || input.populationId <= 0) {
    errors.push("Välj en population")
  } else if (input.populationSize <= 0) {
    errors.push("Populationen har inga personas")
  }
  if (!input.seed.trim()) {
    errors.push("Ange en seed")
  }
  if (!input.startDate.trim()) {
    errors.push("Ange startdatum")
  }
  if (input.mainTicks.length === 0) {
    errors.push("Tidslinjen behöver minst en dag/tick")
  }

  input.mainTicks.forEach((tick, i) => {
    validateTick(tick, `Dag ${tick.day} (tick ${i + 1})`, errors)
  })

  const branch = input.branch
  if (branch) {
    if (branch.afterIndex < 0 || branch.afterIndex >= input.mainTicks.length) {
      errors.push("Delningspunkten pekar utanför huvudtidslinjen")
    }
    if (branch.a.length === 0) {
      errors.push("Version A behöver minst en tick")
    }
    if (branch.b.length === 0) {
      errors.push("Version B behöver minst en tick")
    }
    branch.a.forEach((tick, i) => {
      validateTick(tick, `Version A · dag ${tick.day} (tick ${i + 1})`, errors)
    })
    branch.b.forEach((tick, i) => {
      validateTick(tick, `Version B · dag ${tick.day} (tick ${i + 1})`, errors)
    })
  }

  return { ok: errors.length === 0, errors }
}
