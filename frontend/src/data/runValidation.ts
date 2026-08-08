import type { BranchState, Injection, Tick } from "@/data/runs-types"
import type { MessageKey, TranslateParams } from "@/i18n"

export type RunConfigValidation = {
  ok: boolean
  errors: string[]
}

type Translate = (key: MessageKey, params?: TranslateParams) => string

function injectionHasContent(injection: Injection): boolean {
  if (injection.mode === "link" && injection.url.trim()) return true
  return Boolean(injection.text.trim())
}

function validateTick(
  tick: Tick,
  label: string,
  errors: string[],
  t: Translate,
): void {
  if (tick.rounds < 1) {
    errors.push(t("runs.validation.roundsMin", { label }))
  }
  if (tick.silent) return
  const withContent = tick.injections.filter(injectionHasContent)
  if (withContent.length === 0) {
    errors.push(t("runs.validation.needMessage", { label }))
  }
}

/** Domain checks before start — not OASIS/API/engine plumbing. */
export function validateRunConfig(
  input: {
    name: string
    populationId: number | null
    populationSize: number
    startDate: string
    mainTicks: Tick[]
    branch: BranchState | null
  },
  t: Translate,
): RunConfigValidation {
  const errors: string[] = []

  if (!input.name.trim()) {
    errors.push(t("runs.validation.nameRequired"))
  }
  if (input.populationId == null || input.populationId <= 0) {
    errors.push(t("runs.validation.populationRequired"))
  } else if (input.populationSize <= 0) {
    errors.push(t("runs.validation.populationEmpty"))
  }
  if (!input.startDate.trim()) {
    errors.push(t("runs.validation.startDateRequired"))
  }
  if (input.mainTicks.length === 0) {
    errors.push(t("runs.validation.timelineEmpty"))
  }

  input.mainTicks.forEach((tick, i) => {
    validateTick(
      tick,
      t("runs.validation.tickLabel", { day: tick.day, index: i + 1 }),
      errors,
      t,
    )
  })

  const branch = input.branch
  if (branch) {
    if (branch.afterIndex < 0 || branch.afterIndex >= input.mainTicks.length) {
      errors.push(t("runs.validation.splitOutOfRange"))
    }
    if (branch.a.length === 0) {
      errors.push(t("runs.validation.versionAEmpty"))
    }
    if (branch.b.length === 0) {
      errors.push(t("runs.validation.versionBEmpty"))
    }
    branch.a.forEach((tick, i) => {
      validateTick(
        tick,
        t("runs.validation.versionATick", { day: tick.day, index: i + 1 }),
        errors,
        t,
      )
    })
    branch.b.forEach((tick, i) => {
      validateTick(
        tick,
        t("runs.validation.versionBTick", { day: tick.day, index: i + 1 }),
        errors,
        t,
      )
    })
  }

  return { ok: errors.length === 0, errors }
}

export type RunWizardStep = 1 | 2 | 3 | 4

/** Per-step validation for the create wizard — steps 3–4 have no "next" gate. */
export function validateRunWizardStep(
  step: RunWizardStep,
  input: {
    name: string
    populationId: number | null
    populationSize: number
    startDate: string
    mainTicks: Tick[]
    branch: BranchState | null
  },
  t: Translate,
): RunConfigValidation {
  const errors: string[] = []

  if (step === 1) {
    if (!input.name.trim()) {
      errors.push(t("runs.validation.nameRequired"))
    }
    if (input.populationId == null || input.populationId <= 0) {
      errors.push(t("runs.validation.populationRequired"))
    } else if (input.populationSize <= 0) {
      errors.push(t("runs.validation.populationEmpty"))
    }
    if (!input.startDate.trim()) {
      errors.push(t("runs.validation.startDateRequired"))
    }
    return { ok: errors.length === 0, errors }
  }

  if (step === 2) {
    if (input.mainTicks.length === 0) {
      errors.push(t("runs.validation.timelineEmpty"))
    }
    input.mainTicks.forEach((tick, i) => {
      validateTick(
        tick,
        t("runs.validation.tickLabel", { day: tick.day, index: i + 1 }),
        errors,
        t,
      )
    })
    const branch = input.branch
    if (branch) {
      if (branch.afterIndex < 0 || branch.afterIndex >= input.mainTicks.length) {
        errors.push(t("runs.validation.splitOutOfRange"))
      }
      if (branch.a.length === 0) {
        errors.push(t("runs.validation.versionAEmpty"))
      }
      if (branch.b.length === 0) {
        errors.push(t("runs.validation.versionBEmpty"))
      }
      branch.a.forEach((tick, i) => {
        validateTick(
          tick,
          t("runs.validation.versionATick", { day: tick.day, index: i + 1 }),
          errors,
          t,
        )
      })
      branch.b.forEach((tick, i) => {
        validateTick(
          tick,
          t("runs.validation.versionBTick", { day: tick.day, index: i + 1 }),
          errors,
          t,
        )
      })
    }
    return { ok: errors.length === 0, errors }
  }

  // Step 3 (tools) and 4 (review): no gate — tools are optional.
  return { ok: true, errors: [] }
}
