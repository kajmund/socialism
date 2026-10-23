# B4b – Fullt live-arm med hybrid kandidatgenerering

Type: task
Status: resolved
Blocked by: 22

## Question

Förbättrar hybrid kandidatgenerering den slutliga beslutskvaliteten — inte bara
Candidate Recall — utan att false-sufficient, coverage eller Jev-kostnad
försämras?

- A: deterministisk kandidatgenerering + nuvarande ranking.
- B: hybrid (deterministisk ∪ embeddings) + nuvarande ranking.
- Två live-repetitioner, samma A3-kontrakt och 40-parsbudget.
- Mät: decision_correctness, false-sufficient, false-insufficient,
  evidence_coverage, Candidate Recall, Recall@Budget, Jev-anrop, latens,
  unika relevanta motsägelser per fall (inte bara händelser).
- Förregistrerat adoptionskriterium: B får ersätta deterministisk generering
  endast om decision_correctness är minst lika bra, false-sufficient inte ökar,
  coverage inte försämras och Jev-anropen inte ökar. Candidate Recall ensam är
  inte tillräckligt.
- SSR/ankare får inte ingå i denna arm; de testas separat efteråt.

Ingen produktionsändring; PR #426 orörd.

## Låst protokoll före körning (2026-10-23)

**Huvudarmar:** A deterministisk generering, B hybrid (deterministisk ∪
embeddings). Oförändrad ranking (nuvarande ordning), Jev-logik och 40-parsbudget.
Två live-repetitioner. SSR ingår inte.

**Sido vid sido:** Candidate Recall (finns paret i kandidatmängden?) och
Recall@40 (finns det bland de 40 valda?) per fall, så att genereringseffekten
isoleras från ranking.

**Dessutom:** unika relevanta motsägelser per fall (inte detektionshändelser),
antal Jev-anrop, latens, embeddinganrop, kandidatvolym, valda par och
`jev_calls_per_useful_facit_pair`.

**Adoptionskriterium (förregistrerat):** B får ersätta deterministisk generering
endast om decision_correctness är minst lika bra, false-sufficient inte ökar,
coverage inte försämras, Jev-anropen inte ökar och Candidate Recall inte
försämras. Candidate Recall ensam räcker inte. Om B inte förbättrar
slutbesluten behålls deterministisk generering även om recall ökar.

## Answer

**Körd 2026-10-23** (commit `6b8d311b`), två live-repetitioner per arm,
oförändrad ranking, Jev-logik och 40-parsbudget.

| Mått | A deterministisk | B hybrid |
| --- | ---: | ---: |
| Rätt / 26 | 16 | **22** |
| False-sufficient | 6 | **0** |
| Coverage complete | 22 | 22 |
| Candidate Recall (kända par) | 8 | **14** |
| Recall@40 | 6 | **12** |
| Unika konflikter | 4 | 9 |
| Valda användbara facitpar | 3 | 6 |
| Jev-anrop | 2 320 | 2 336 (+0,7 %) |
| Latens | 161 s | 185 s |
| Embeddinganrop/texts | 0 / 0 | 24 / 500 |

De tre syntetiska lågoverlappande motsägelserna visar den direkta
omvandlingen från Candidate Recall till beslut: A ger `sufficient` i alla sex
fall/repetitioner; B ger `insufficient` i alla sex, med både Candidate Recall
och Recall@40 sanna. `late_evidence` är `insufficient` i båda armarna och det
kända paret missar fortfarande topp 40 — rankning är late-flaskhalsen.
Hybrid rättar inte compatible-fallens false-insufficient.

**Förregistrerat beslut:** `KEEP_DETERMINISTIC` eftersom kriteriet
`jev_calls_not_higher` fallerar (2 336 mot 2 320, +0,7 %). Artefakten behåller
detta. Men kvalitetsvinsten är stor: sex färre false-sufficient för 16 extra
anrop. Det kräver ett **explicit adoptionsbeslut** (ticket 25), inte en tyst
ändring av kriteriet.
