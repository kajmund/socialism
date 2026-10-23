# B1 – Shadow-jämförelse av narrativ precheck

Type: grilling
Status: resolved
Blocked by: 11

## Question

Kan den narrativa prechecken, utan beslutsmakt, tillföra något utöver A3 på ett
skärpt gap-facit?

- Skärp rapportkontraktet: kräv att varje flaggat gap pekar på evidens/claims i
  payloaden och på ett gap som A3 inte redan har täckt; gör `needs_more_evidence`
  svårare att sätta.
- Definiera ett gap-facit per fryst fall (vilka luckor som faktiskt finns) och
  mät precision/recall, inte bara flaggbenägenhet.
- Kör B0-prechecken i shadow mot A3 med oförändrad dom; mät om den hittar
  evidens A3 missar, false alerts och extra kostnad.
- Beslutskriterium: hittar den verkliga luckor som A3 missar utan oacceptabel
  falsk flaggning? Om inte, förkasta B1 eller omdefiniera prechecken.

Ingen beslutsrätt, ingen produktionsändring. A3 artefakter är referens.

## Answer

**Körd 2026-10-23** i commit `fe53fd51`. Shadow-only; A3 är oförändrad
jämförelsearm och B har ingen beslutsrätt.

### Implementerat

- Fyra utfall: `VERIFIED_GAP`, `SUSPECTED_GAP`, `NO_GAP_FOUND`, `UNDETERMINED`.
  `NO_GAP_FOUND` bevisar aldrig fullständighet.
- Varje gap: `need_id`, vad som saknas, motiverande observationer, tillåtet
  workflow och ankare (`claim:`, `pair:`, `coverage:`, `aggregation:`).
- Deterministisk validator (`gap_contract.validate_gap_report`) avvisar okända
  needs/workflows/ankare och degraderar trasig `VERIFIED_GAP` till
  `UNDETERMINED`. `SUSPECTED_GAP` har ingen exekveringsväg.
- Explicit antikautel i prompten: gap får inte rapporteras enbart för att mer
  evidens teoretiskt kunde finnas.
- Deterministisk baseline från samma coverage-metadata, noll LLM-anrop, för
  jämförelse.

### Resultat (ett live-varv, 11 fall)

| Detektor | TP | FP | FN | TN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Narrativ B1 | 2 | 4 | 0 | 1 | 0.33 | 1.00 |
| Deterministisk metadata | 2 | 2 | 0 | 3 | 0.50 | 1.00 |

Kostnad: 11 LLM-anrop, ~34 400 inmatningstecken, ~7,9 s gap-latens, 1 153
A3-Jev-anrop. Deterministiska baselineen: 0 LLM-anrop.

Acceptanskriterier:

| Kriterium | Utfall |
| --- | --- |
| `late_evidence` identifieras | **ja** (`SUSPECTED_GAP`) |
| `short_sufficient` inte `VERIFIED_GAP` | **ja** (`NO_GAP_FOUND`) |
| Varje `VERIFIED_GAP` har maskinellt giltiga ankare | **nej** — 2 av 10 använde påhittade `coverage:`-ankare och avvisades |
| `SUSPECTED_GAP` triggar ingen exekvering | ja (ingen väg) |
| A3:s beslut opåverkat | ja |

### Slutsats

B1 gör gap-bedömningen falsifierbar, men den narrativa modellen slår **inte** den
kostnadsfria deterministiska baselineen: samma recall, sämre precision, och den
flaggar `compatible_*` samt redan lösta konflikter (`duplicate`/`independent`)
som gap. Ankaracceptansen fallerade. Därför får B2 **inte** påverka exekvering
ännu.

Nästa steg är B1b: härda ankar- och negativfallspolicyn, lägg till fler
positiva/negativa gap-fall och kör om narrative mot deterministisk baseline.
