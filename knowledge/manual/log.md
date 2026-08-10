# Manual update log

## 2026-08-09

* **Personas**: Biblioteket kan filtreras och sorteras på demografiska fält (kön, distrikt, yrke, utbildning, livssituation; sortering även på ålder).

## 2026-08-07

* **Playground**: Ny guide för att kalibrera anchors, jämföra SSR mot nyckelord och iterera prompter från konfigurationer.
* **Playground**: Temperatur (softmax) dokumenterad för anchor-kalibrering och SSR vs nyckelord.
* **Konfigurationer**: SSR-temperatur under Rapport i promptinställningar (styr skarpa rapporter).
* **Verktyg**: Konfigurationer, playground och embedding-cache samlade under menyn Verktyg; guide för att rensa cache.
* **Playground**: Flik för att testa agentverktyg (webbsök / SymPy) utan full simulering.
* **Körningar**: Agentverktyg väljs granulärt (DuckDuckGo / Wikipedia / SymPy) med eget wizardsteg och Välj alla.
* **Rapporter**: Beställa/läsa rapport beskriver Snabbrapport vs Full rapport (SSR-mall vs längre hybridrapport).

## 2026-08-06

* **Jobs**: Clarified that Bakgrundsjobb updates live when status changes (no polling wording).
* **Configurations / grunddata**: Grunddata is per configuration (Promptinställningar + Grunddata tabs); removed standalone Konfiguration nav; active config drives both prompts and catalog lists.


## 2026-08-05

* **Initialization**: Created OKF manual bundle with seed guides for overview, create run, and start simulation.
* **Backfill**: Added 16 guides covering runs list, tick config, results, reports, personas, populations, messages, grunddata, jobs, and simulator demo.
* **Removal**: Dropped the paper demo simulator guide (`anvanda-simulatorn.md`) and related overview/index links after `/simulator` was removed from the product.
* **Configurations**: Added guide for managing saved prompt configurations (`hantera-konfigurationer.md`) and linked it from the index and overview.
* **Configurations**: Updated guide for multi-field prompt sets (persona/chat/messages/OASIS/report) and activating the config used by backend.
