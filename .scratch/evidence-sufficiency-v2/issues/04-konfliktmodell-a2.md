# Konfliktmodell och lösningsprovenance (A2)

Type: grilling
Status: resolved
Blocked by: 03

## Question

Hur ska A2 skilja på dubblett, oberoende källa, motsägelse och löst konflikt —
och vad krävs för att en motsägelse får markeras som löst?

Beslut som ticketen ska låsa:

- Kanoniska definitioner för `duplicate`, `independent_source`, `contradiction`
  och `resolved_conflict`. Utmana gärna termerna mot befintlig kod
  (`quality.independence_key`, `likely_duplicate_or_redundant`,
  `resolve_conflict`).
- Vilka skäl får lösa en konflikt? Specen tillåter verifierbar skillnad i
  giltighetstid, tillämpningsområde, definition eller refererad entitet. Vad
  räknas som tillräckligt bevis, och vem/vad får bedöma det (deterministiskt
  fält, Jev-par, temporal relation)?
- Vad får **inte** lösa en konflikt (högt dubblettscore, fler källor på ena
  sidan, högre relevans, samma dokument, kortare/äldre passage utan verifierad
  temporal relation)? Gör listan till regler, inte exempel.
- Vilken post krävs för en lösning: jämförda påståenden, regel/bedömning,
  källunderlag, konfidens, provenance. Var lagras den (ExperimentReport,
  spårartefakt) utan att bli en ny domänmodell?
- Vad gör en `unresolved` konflikt nedströms — gate, route, narrativ — givet
  A1-kontraktet? Får den aldrig försvinna genom subworkflow?
- Acceptansfall: hög redundans + faktisk motsägelse förblir unresolved; fem
  kopior räknas som en källa; historiskt/aktuellt värde hålls isär med styrkt
  tidskontext; motsägelser i olika avtal behandlas inte som samma sak; ingen
  `resolved` utan spårbar motivering.
- Var konfliktposten lever: `ExperimentReport`/spårartefakt eller persistens?
  Inventeringen visar att `CONTRADICTS`-kanten finns men saknar status/regel, att
  `write_fact(contradiction_key=...)` inte har någon anropare och att
  paritetskontrollen kräver `LINKED` medan mirror-mappningen skriver
  `CONTRADICTS` — vilken representation är auktoritativ?

Leverans: A2-kontrakt (termer, regler, post-schema, nedströmsbeteende,
acceptansfall) som kan implementeras utan fler beslut.

## Answer

**Beslut 2026-10-22 (grilling med användaren), med två preciseringar.** Ticketen
stängs först när schema, tester och replay-resultat är färdiga; de är det nu
(commit `8ece2c94` på `feat/sufficiency-a2-conflicts`).

### Precisering 1 – båda sidorna

En konfliktpost har `sides`. Den kan innehålla ett fullständigt par eller en
identifierad passage med okänd motpart. Motparten hittas aldrig på. En konflikt
med okänd motpart (`len(sides) < 2`) kan aldrig bli `resolved` eller
`not_applicable`; den är alltid `unresolved`. Samma schema används i A3 när
riktiga faktapar börjar jämföras (`PassageEvaluation.counterpart_passage_ids` är
kopplingspunkten).

### Precisering 2 – tre statusar

| Status | Betydelse |
| --- | --- |
| `unresolved` | Möjlig eller konstaterad konflikt som inte klarats ut |
| `resolved` | Verklig konflikt med uttryckligt verifierad lösning |
| `not_applicable` | Påståendena gäller olika tid/entitet/definition och motsäger inte varandra |

Även `not_applicable` kräver verifierbart stöd. Den är aldrig en genväg för att
avfärda en motsägelse.

### Post-schema (`types.py`)

`ConflictRecord(conflict_id, need_id, status, sides, resolution, flagged_by)`.
`ConflictSide(evidence_id, passage_id, claim_id, source_id)`.
`ConflictResolution(kind, rule_id, evidence_ids, detail)` med
`kind ∈ {temporal, entity, definition, superseding}`. Posten ligger i
`NeedAggregation.conflicts` och därmed i `ExperimentReport`/spårartefakten — ingen
DB, ingen ny domänmodell.

### Regler (`conflicts.py`)

Endast typad, verifierbar metadata i `AssessableEvidence.provenance` får lösa:

| Regel | Metadata | Status |
| --- | --- | --- |
| `temporal_disjoint_intervals` | `valid_from`/`valid_to` (ISO-8601), icke-överlappande | `not_applicable` |
| `distinct_entity` | `entity_id` skiljer sig | `not_applicable` |
| `distinct_definition` | `definition_id` skiljer sig | `not_applicable` |
| `explicit_supersession` | `superseded_by` pekar på motpartens evidence | `resolved` |

Får **aldrig** lösa: duplicate-score, relevansscore, antal källor, samma dokument,
kortare/äldre passage utan verifierad temporal relation, eller saknad motpart.
`independence_key` är fortsatt enda grunden för oberoende källor (fem kopior = en
källa).

### Nedströms

`unresolved` → `NeedAggregation.status = uncertain`, gate `allows_sufficient =
False`, aldrig `sufficient`; ingen lösnings-subworkflow finns kvar (den
duplicate-baserade `resolve_conflict` och SWE-noden är borttagna).
`resolved`/`not_applicable` tas bort från `unresolved_conflicts` men posten med
regel + bevis finns kvar i rapporten.

### Tester

`tests/test_sufficiency_experiment_conflicts.py`: duplicate 0.89 + motsägelse
0.95 förblir unresolved; ensidig konflikt kan inte lösas; disjunkta
giltighetsperioder → `not_applicable`; olika entiteter → `not_applicable`;
`superseded_by` → `resolved`; par utan metadata → unresolved; saknad
motpartsevaluering → unresolved; stabila/ordningsoberoende conflict-id.
Dessutom uppdaterade aggregat-, policy- och workflowtester.

### Replay-resultat

`scripts/replay_sufficiency_conflicts.py` läser den frysta live-tracen, sätter
kontradiktionsscoren 0.95 på signaturpassagerna och behåller uppmätta
duplicate-scores. Artefakt:
`backend/tests/integration/baselines/sufficiency-conflict-replay-v1.json`.

| Fall | Duplicate | Förced contradiction | Utfall |
| --- | ---: | ---: | --- |
| `tail_counterevidence` | 0.61 | 0.95 | `unresolved` → insufficient/uncertain |
| `late_evidence` | 0.89 | 0.95 | `unresolved` → insufficient/uncertain |
| `large_567k` | 0.94 | 0.95 | `unresolved` → insufficient/uncertain |
| `short_sufficient` (kontroll) | 0.17 | – | sufficient |

Detta är replay över uppmätta scores, inte en ny livekörning. A2 ändrar inte
live-domarna; detektionen är A3:s uppgift.

### Verifiering

48 sufficiency-tester gröna, ruff grön, maintainability grön. Ingen
produktionsfil ändrad; PR #426 orörd.

