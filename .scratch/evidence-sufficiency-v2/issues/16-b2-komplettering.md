# B2 – Workflow-styrd komplettering

Type: grilling
Status: resolved
Blocked by: 15, 18

## Question

Ska SWE, när B1 visar ett verkligt gap, köra en begränsad typad workflow för att
komplettera evidensen — och förbättrar det false-insufficient utan att skapa nya
false-sufficient?

- Vilka allowlistade workflows får köras på ett gap (t.ex. ytterligare
  pargenerering eller evidenssökning) och med vilken budget?
- SWE äger exekvering, budget, parallellism och det verifierbara täckningsbeslutet.
  B får bara föreslå arbetet.
- Mät mot A3: false-insufficient, false-sufficient, kostnad per förbättrat beslut.
- Beslutskriterium: förbättras false-insufficient utan nya false-sufficient?

## Answer

**Aldrig startad.** B1b (ticket 18) avslutade den narrativa grenen:
`END_NARRATIVE_BRANCH` eftersom narrative inte slog den deterministiska
baselineen (incremental gap yield 0, fler false positives, högre kostnad).
B2 skulle ha byggt på en mekanism som inte visat mervärde och avvecklas.
