# Implementera route-auktoritet (A1)

Type: task
Status: resolved
Blocked by: 02

## Question

Implementera A1-kontraktet från ticket 03 i det opt-in experimentet:

- `final_outcome` (`sufficient`/`insufficient`/`uncertain`) på `RouteDecision`.
- Auktoritetspredikat med fyra signaler: `answerable_now`, `material_gap`,
  `contradiction`, `confidence` (min över alla fem NOUL-svar); trösklarna
  oförändrade.
- `FINISH` bär utfallet och får aldrig tolkas som implicit samtycke.
- PASS + `final_outcome=uncertain` → intern `uncertain`, draft `insufficient`,
  reason `route_uncertain`; PASS + insufficient → `insufficient`; PASS utan
  giltigt utfall → `failed`.
- Programmatic-vägen undantas.
- `follow_up_change`/`additional_source` får inte veto:a sufficient och kan
  aldrig åsidosätta ett ouppfyllt krav i den deterministiska grinden.

Leverans: kod + ticket 03:s testmatris + ett scriptat A0-vs-A1-artefakt som
visar att PASS + route-uncertain inte längre blir `sufficient` (och att
`short_sufficient` förblir sufficient). Ingen produktionsändring, ingen ändring
av PR #426.

## Answer

**Implementerad 2026-10-23** i commit `72819568`. Inga produktionsändringar;
PR #426 orörd.

### Kontrakt

- `RouteDecision.final_outcome` (`sufficient`/`insufficient`/`uncertain`).
- `authoritative_outcome`: fyra signaler — `answerable_now`, `material_gap`,
  `contradiction`, `confidence` (min över alla fem NOUL-svar). Trösklarna
  oförändrade (0.9 / 0.1 / 0.8).
- `follow_up_change`/`additional_source` kan varken auktorisera eller veto:a
  `sufficient`, och kan inte åsidosätta ett ouppfyllt gate-krav.
- `status_from_route`: PASS+sufficient → sufficient; PASS+insufficient →
  insufficient; PASS+uncertain → uncertain + insufficient draft; FINISH utan
  utfall eller avvisad sufficient → fail-closed; programmatic-vägen undantas.
- `FINISH` utan utfall avvisas av `validate_route` (`FINISH without final
  outcome`).

### Arm-toggles (experiment-only)

`route_authority` (A1), `legacy_duplicate_resolution` (A0-beteende) och
`pair_judgement` (A3). Default är modern A3-väg; A0/A1-armerna sätter dem
explicit i mätningen. `legacy_duplicate_resolution` hoppar över
duplicate-flaggade passagekonflikter, vilket återger A0:s utfall utan att
återinföra den borttagna resolvern i produktionslogiken.

### Scriptat A0-vs-A1-artefakt

`tests/integration/baselines/sufficiency-a1-route-authority-v1.json`:

| Scenario | A0 | A1 |
| --- | --- | --- |
| route_uncertain (answerable 0.85) | sufficient | insufficient / uncertain |
| route_insufficient (gap 0.95) | sufficient | insufficient |
| route_sufficient | sufficient | sufficient |

Inga live-anrop; artefakten mäter enbart auktoritetsändringen.

### Verifiering

`tests/test_sufficiency_experiment_a1.py` (5 tester): fyra-signalers predikat,
FINISH utan utfall avvisas, avvisad sufficient, A0 ignorerar route-osäkerhet medan
A1 inte gör det, A1 uppgraderar aldrig en FAIL-gate. 102 sufficiency-tester
gröna, ruff och maintainability gröna. Två reuse-tester uppdaterade till A1:s
eskaleringsstatus (`uncertain` vid obunden narrativ) med bibehållen draft.
