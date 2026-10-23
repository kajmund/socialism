# B1b – Härda gap-kontraktet och negativa fall

Type: task
Status: resolved
Blocked by: 15

## Question

Gör B1:s gap-bedömning tillförlitlig nog att B2 får pröva komplettering.

- Ankarpolicy: varje `VERIFIED_GAP` måste referera till existerande claim-,
  pair-, coverage- eller aggregation-id; påhittade `coverage:`-orsaker ska
  avvisas redan i schemat (inte bara i efterhand).
- Lägg till minst två positiva och tre negativa gap-fall utöver
  `late_evidence`/`missing_source_type` respektive `short_sufficient`/
  `compatible_*`. Dokumentera facit per fall.
- Kör om narrative B1 mot den deterministiska baselineen med samma fall och
  redovisa precision, recall, FP, latens och LLM-/Jev-kostnad separat.
- Krav före B2: alla `VERIFIED_GAP` har giltiga ankare, `short_sufficient` och
  `compatible_*` är `NO_GAP_FOUND`/`UNDETERMINED` utan kompletteringsförslag,
  och narrative slår deterministisk baseline på minst ett relevant mått utan
  oacceptabel kostnad. Annars förkasta narrativ gap-detektion.

Ingen beslutsrätt, ingen produktionsändring; A3 orörd.

## Protocol (låst före körning, 2026-10-23)

**Ett enda kontrollerat härdningsförsök.** Inga fler promptiterationer efter
detta utan ny ticket.

Mått som redovisas separat och explicit, inklusive exkluderade fall:

- Gap precision/recall (endast klassificerade positiva/negativa fall).
- Valid report rate (`validated_verdict != UNDETERMINED`).
- Unsupported anchor rate (gap med ankare utanför `available_anchors` eller
  fel need).
- False workflow proposal rate (negativa fall som föreslår komplettering).
- Incremental gap yield (narrativa TP som deterministiska baselineen missar).
- Marginal cost per useful gap (LLM-anrop och latens per inkrementellt gap).

Avslutskriterium:

- **CONTINUE_TO_B2** om incremental yield ≥ 1, narrativa FP ≤ deterministiska
  FP + 1, valid report rate ≥ 0.9 och unsupported anchor rate = 0.
- **RETIRE_NARRATIVE_GAP_DETECTION** om incremental yield = 0 och ingen
  kvalitetsvinst över baseline.
- **END_NARRATIVE_BRANCH** om narrative är sämre (lägre precision/fler FP);
  prioritera då B3.

## Answer

**Körd 2026-10-23** (commit `a201ae7d`) enligt det förregistrerade protokollet.
Ingen beslutsrätt; A3 orörd.

### Klassificering

12 klassificerade fall: 4 positiva (2 live, 2 syntetiska), 8 negativa (5 live,
3 syntetiska). 4 neutrala fall exkluderades explicit från precision/recall:
`tail_counterevidence`, `large_567k`, `unknown_counterpart`,
`tail_claim_contradiction`.

### Resultat

| Detektor | TP | FP | FN | TN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Narrativ B1b | 4 | 6 | 0 | 2 | 0.40 | 1.00 |
| Deterministisk metadata | 4 | 5 | 0 | 3 | 0.44 | 1.00 |

| Förregistrerat mått | Utfall |
| --- | ---: |
| Valid report rate | 0.917 |
| Unsupported anchor rate | 0.125 |
| False workflow proposal rate | 0.875 |
| Incremental gap yield | **0** |
| Marginal cost per useful gap | odefinierad (inga inkrementella gap) |
| LLM-/Jev-kostnad | 16 LLM-anrop, ~46 000 tecken, 10,0 s gap-latens, 1 170 Jev-anrop |

### Beslut: `END_NARRATIVE_BRANCH`

Narrative matchar deterministisk recall men har fler falska positiva, föreslår
komplettering i 7 av 8 negativa fall, producerar fortfarande icke-stödda ankare
och hittar **noll** gap som den kostnadsfria baselineen missar. Marginalkostnaden
per användbart gap är oändlig eftersom inget sådant gap finns.

Syntetiska clean-fall fastnade i obligation-incomplete state, så de isolerar
inte ett coverage-komplett semantiskt gap; det live-förregistrerade setet driver
avvisningen. Det ändrar inte beslutsregeln: narrative är inte bättre.

**Konsekvens:** B2 byggs inte. Den narrativa gap-grenen avvecklas som generell
mekanism. B3 – adaptivt urval av faktapar – är nästa SWE-experiment.
