# Kör armjämförelsen enligt protokollet

Type: task
Status: resolved
Blocked by: 10, 13

## Question

Kör A0/A2/A3 (och A1 när ticket 13 är klar) enligt det låsta protokollet:

- Parad referens per arm från Jev-kassett, i samma ordning. Armordningen är
  låst till `A0, A2, A3, A1` i förregistreringen och får inte sorteras om.
- Rapportens jämförelsematris: A0–A1 parade svar (beslutslogik), A1–A2 parade
  där anropssignaturen matchar (konflikthantering), A2–A3 nya faktaparsanrop
  (hela metoden inklusive nya modellanrop). Saknade kassettposter rapporteras
  som `reproducibility_error`, aldrig som modellfel.
- Två oberoende live-repetitioner per arm för operativ kvalitet.
- Frysta A0-artefaktet lämnas orört; en ny parad A0-referens mäts.
- Skriv `arm-<arm>-<date>.json` med semantiska/operativa mått, kostnad,
  coverage-status per nivå och PASS/FAIL mot `measurement-protocol-v1.json`.
- Ingen produktionsändring, ingen höjning av 40-parsbudgeten, ingen ändring av
  PR #426.

Leverans: armartefakter + PASS/FAIL-tabell redo för ticket 12:s slutgranskning.

## Answer

**Körd 2026-10-23** enligt `measurement-protocol-v1.json`. Commit `5f30d750`.
Inga produktionsändringar; PR #426 orörd.

### Upplägg

10 fall (fyra A0 + fem konflikt + tail_claim_contradiction), två
live-repetitioner per arm, armordning **A0 → A2 → A3 → A1** exakt som
förregistrerat. A0 spelades in först; A1/A2 spelade upp matchande anrop (A1 ska
vara helt parad), A3 körde nya faktapars- och routeanrop live. A0 fick tekniska
fel i båda repen (2 fel per rep), vilket syns i den operativa statistiken.

Kassettparning rep 0:

| Arm | Matchade | Live | Klassning |
| --- | ---: | ---: | --- |
| A1 | 1 060 | 6 | `reproducibility_error` (A0-inspelningens gap) |
| A2 | 1 060 | 6 | samma gap |
| A3 | 1 056 | 95 | 44 faktaparsanrop + nya routeanrop + A0-gapen |

A1:s 6 live-anrop är **inte** modellfel; de är luckor i A0-inspelningen och
rapporteras som reproducerbarhetsfel enligt protokollet.

### Semantisk kvalitet (rena körningar)

| Arm | Accuracy | False-sufficient | False-insufficient | TP-konflikter | Falska motsägelser |
| --- | ---: | ---: | ---: | ---: | ---: |
| A0 | 0.24 | 0.82 | 0.67 | 0 | 0 |
| A1 | 0.32 | 0.69 | 0.67 | 0 | 0 |
| A2 | 0.26 | 0.77 | 0.67 | 0 | 0 |
| A3 | **0.73** | **0.00** | 0.67 | 6 | 0 |

### Operativ kvalitet

A3: raw accuracy 0.80, operational success 0.55, teknisk felkvot 0.05,
`sufficient_on_failed_call=0`, inga oförklarade verdict-skillnader. A0: raw
0.35, operational success 0.20, felkvot 0.15; `late_evidence` instabil mellan
repen men förklarad av tekniskt fel. A1/A2: felkvot 0.05.

### Varför domarna föll (rep 0)

| Fall | A0 | A1 | A2 | A3 |
| --- | --- | --- | --- | --- |
| tail_counterevidence | sufficient | sufficient | sufficient | insufficient, **motsägelse detekterad** |
| late_evidence | tekniskt fel | sufficient | sufficient | insufficient, **endast coverage** |
| duplicate_contradiction | sufficient | sufficient | sufficient | insufficient, **motsägelse detekterad** |
| independent_contradiction | sufficient | sufficient | sufficient | insufficient, **motsägelse detekterad** |

**Nyckelsvaret:** A3 löser `tail_counterevidence`, `duplicate_contradiction` och
`independent_contradiction` genom verklig faktaparsdetektion.
`late_evidence` löses **inte** av detektion — där finns inget par-konflikt; det
är den ofullständiga par-coverage:n (40-parsbudgeten) som får systemet att faila
closed. Det är ett coverage-/kostnadsresultat, inte evidensförståelse.

A1 ändrade inte live-fällorna: de fyra auktoritetssignalerna var starka, så
routeutfallet var `sufficient`. Det scriptade A0-vs-A1-artefakten visar
kontraktet i det läge där route faktiskt är osäker.

### Kostnad

A3: 2 302 Jev-anrop vs A0 2 132 (+170 över två rep), 6 upptäckta
motsägelser, `cost_per_detected_contradiction` 384 anrop,
`cost_per_correct_decision` 209. A3 tar bort alla false-sufficient i rep 0 men
har fortsatt 0.67 false-insufficient (coverage på stora underlag samt
compatible-fallens overifierade stöd) — det är inte en gratis vinst.

### PASS/FAIL

Alla förregistrerade checks i körningen: `a1_route_uncertain_never_sufficient`,
`a3_traps_not_sufficient`, `a3_short_sufficient`, `a3_compatible_clean`,
`no_silent_success_on_failure`, `a3_budget_unchanged` → **true**.

### Kvarstående diagnostik

A1:s `confidence` är fortsatt min över alla fem NOUL-svar; `follow_up`/
`additional` kan därför indirekt påverka sufficient genom confidence. Det syns
ännu inte i armartefakterna och ska läggas till i slutplanen (ticket 12).

### Artefakter

`arm-comparison-v1.json`, `arm-A0/A1/A2/A3-2026-10-23.json`,
`jev-cassette-a0-2026-10-23.json`, drivrutin
`scripts/run_arm_comparison.py`.
