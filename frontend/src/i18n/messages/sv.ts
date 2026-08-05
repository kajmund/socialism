/** Nested string catalog — keys come from the Swedish tree. */
export type MessageTree = {
  [key: string]: string | MessageTree
}

/** Swedish UI copy — source of truth for message keys. */
export const sv = {
  brand: {
    product: "Opinionssimulator",
  },
  nav: {
    ariaMain: "Huvudmeny",
    personas: "Personas",
    populations: "Populationer",
    messages: "Budskap",
    config: "Konfiguration",
    runs: "Körningar",
    jobs: "Bakgrundsjobb",
    simulator: "Simulator",
    activeJobs: "{count} aktiva jobb",
  },
  locale: {
    switcherLabel: "Språk",
    sv: "Svenska",
    en: "English",
  },
  common: {
    open: "Öppna",
    emDash: "—",
  },
  toast: {
    simulationDone: "Simuleringen »{label}« är klar",
    reportDone: "Rapporten »{label}« är klar",
    jobDone: "Jobbet »{label}« är klart",
    simulationFailed: "Simuleringen »{label}« misslyckades{detail}",
    reportFailed: "Rapporten »{label}« misslyckades{detail}",
    jobFailed: "Jobbet »{label}« misslyckades{detail}",
    openResults: "Öppna resultat",
    openReport: "Öppna rapport",
    openPopulation: "Öppna population",
    viewJobs: "Visa jobb",
    openRun: "Öppna körning",
  },
  jobs: {
    kicker: "Bakgrundsjobb",
    title: "Jobb",
    intro: "Generering och andra långa körningar utan tidsbegränsning i webbläsaren.",
    empty: "Inga bakgrundsjobb ännu.",
    loadError: "Kunde inte hämta jobb",
    created: "skapad {when}",
    took: "tog {duration}",
    started: "startad {when}",
    openPopulation: "Öppna population →",
    openResults: "Öppna resultat →",
    openReport: "Öppna rapport →",
    openRun: "Öppna körning →",
    personasCount: "{count} personas",
    status: {
      pending: "Väntar",
      running: "Kör",
      succeeded: "Klar",
      failed: "Misslyckades",
    },
    kind: {
      population_generate: "Populationsgenerering",
      run_simulate: "Simulering",
      report_generate: "Rapport",
    },
    progress: {
      queued: "I kö…",
      generating: "Genererar…",
      simulating: "Simulerar…",
      reporting: "Genererar rapport…",
    },
    duration: {
      seconds: "{n} s",
      minutes: "{m} min",
      minutesSeconds: "{m} min {s} s",
      hours: "{h} h",
      hoursMinutes: "{h} h {m} min",
    },
  },
} as const satisfies MessageTree

export type SvMessages = typeof sv
