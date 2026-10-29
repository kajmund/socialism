# Beslutsdiagnostik: separera orsakerna till insufficient

Type: grilling
Status: resolved
Blocked by: 19

## Question

Kan SWE exponera varför ett beslut blev `insufficient` utan att ändra
beslutssemantiken?

Föreslagna maskinellt läsbara orsaker (inte ömsesidigt uteslutande):
`CONTRADICTION_FOUND`, `COVERAGE_INCOMPLETE`, `SUPPORT_INCOMPLETE`,
`TECHNICAL_FAILURE`, `SUFFICIENT`.

- Behåll nuvarande slutkontrakt; lägg endast till separata orsaker.
- Mät unika relevanta motsägelser per fall, inte antal detektionshändelser över
  repetitioner.
- Skilj på två uppdrag med olika stoppvillkor: (a) fastställa att evidensen är
  konfliktfylld, (b) kartlägga alla konflikter. En verifierad avgörande
  motsägelse kan räcka för (a) men inte för (b).
- Ändra inte beslutslogiken utan eget test; diagnostiken ska först mätas och
  jämföras mellan armarna.

Ingen produktionsändring.

## Answer

**Implementerad och diagnostiserad 2026-10-23** (commit `18562447`). Inga
beslutssemantiska ändringar; slutkontraktet är oförändrat.

Rapporten exponerar nu `decision_diagnostics.reasons` (additiva, får överlappa):
`CONTRADICTION_FOUND`, `COVERAGE_INCOMPLETE`, `SUPPORT_INCOMPLETE`,
`TECHNICAL_FAILURE`, `SUFFICIENT`, samt `unique_conflicts` (unika
konflikt-id:n, inte detektionshändelser). `narrative_unbound` räknas inte som
tekniskt fel.

### De fyra kvarvarande felbesluten

Alla fyra är `compatible_periods`/`compatible_entities`, två rep vardera:

| Fält | Värde |
| --- | --- |
| draft / status | insufficient / uncertain |
| orsaker | `SUPPORT_INCOMPLETE` |
| quality reasons | `obligations_unverified` |
| relevance / factual_support | overifierade, independent support 0 |
| parbedömning | SCOPE_DIFFERENCE (korrekt, ingen konflikt) |
| coverage | komplett |
| unika konflikter | inga |

Slutsats: de återstående felen är **stödverifiering/aggregering**, inte
konfliktdetektion eller täckning. Jev bedömer paret korrekt som scope-skillnad,
men relevance- och factual_support-obligationerna verifieras aldrig, så de
förenliga fallen failar closed.

### Nästa steg

- Ticket 28: undersök och åtgärda varför relevance/factual_support inte
  verifieras för dessa fall.
- Ticket 29: separera de två stoppvillkoren (fastställd konflikt vs fullständig
  konfliktkartläggning) — först efter 28.
- SSR (ticket 27/19) väntar tills verifierade sakfrågeankare och utökat facit
  finns.
