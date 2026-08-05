import type { SvMessages } from "./sv"

/** Same shape as Swedish catalog, with string leaves (not Swedish literals). */
type LocalizedTree<T> = {
  [K in keyof T]: T[K] extends string ? string : LocalizedTree<T[K]>
}

/** English UI copy — must mirror every key in `sv`. */
export const en: LocalizedTree<SvMessages> = {
  brand: {
    product: "Opinion simulator",
  },
  nav: {
    ariaMain: "Main navigation",
    personas: "Personas",
    populations: "Populations",
    messages: "Messages",
    config: "Configuration",
    runs: "Runs",
    jobs: "Background jobs",
    simulator: "Simulator",
    activeJobs: "{count} active jobs",
  },
  locale: {
    switcherLabel: "Language",
    sv: "Svenska",
    en: "English",
  },
  common: {
    open: "Open",
    emDash: "—",
  },
  toast: {
    simulationDone: "Simulation “{label}” is done",
    reportDone: "Report “{label}” is ready",
    jobDone: "Job “{label}” is done",
    simulationFailed: "Simulation “{label}” failed{detail}",
    reportFailed: "Report “{label}” failed{detail}",
    jobFailed: "Job “{label}” failed{detail}",
    openResults: "Open results",
    openReport: "Open report",
    openPopulation: "Open population",
    viewJobs: "View jobs",
    openRun: "Open run",
  },
  jobs: {
    kicker: "Background jobs",
    title: "Jobs",
    intro: "Generation and other long-running work without browser timeouts.",
    empty: "No background jobs yet.",
    loadError: "Could not load jobs",
    created: "created {when}",
    took: "took {duration}",
    started: "started {when}",
    openPopulation: "Open population →",
    openResults: "Open results →",
    openReport: "Open report →",
    openRun: "Open run →",
    personasCount: "{count} personas",
    status: {
      pending: "Pending",
      running: "Running",
      succeeded: "Done",
      failed: "Failed",
    },
    kind: {
      population_generate: "Population generation",
      run_simulate: "Simulation",
      report_generate: "Report",
    },
    progress: {
      queued: "Queued…",
      generating: "Generating…",
      simulating: "Simulating…",
      reporting: "Generating report…",
    },
    duration: {
      seconds: "{n} s",
      minutes: "{m} min",
      minutesSeconds: "{m} min {s} s",
      hours: "{h} h",
      hoursMinutes: "{h} h {m} min",
    },
  },
}
