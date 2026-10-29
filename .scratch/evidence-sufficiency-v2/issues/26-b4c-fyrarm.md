# B4c – Fyrarmsfaktorial: generering × prioritering

Type: task
Status: resolved
Blocked by: 25

## Question

Samverkar hybrid kandidatgenerering (B4b) och metadata-prioritering (B3) bättre
än var för sig, och vilken kombination ska vara referens för SSR?

Armar:

| Arm | Generering | Prioritering |
| --- | --- | --- |
| A | Deterministisk | Nuvarande |
| B | Hybrid | Nuvarande |
| C | Deterministisk | Metadata |
| D | Hybrid | Metadata |

Två live-repetitioner per arm, samma A3-kontrakt och 40-parsbudget.

**Mät:** decision_correctness, false-sufficient, coverage, Candidate Recall,
Recall@40, unika konflikter, Jev-anrop och latens **uppdelad** på
embeddingberäkning, kandidatgenerering, prioritering och Jev-exekvering.
Embeddings ska återanvändas när de redan finns.

**Förregistrerat referensval:** D får bli SSR-referens endast om D har högst
decision_correctness, lägst false-sufficient, coverage som inte är sämre och
Recall@40 som inte är sämre än övriga armar. Annars väljs den arm som bäst
uppfyller besluts kvalitet; metadata får inte antas fungera i kombination utan
mätning. Ingen produktionsändring; PR #426 orörd.

## Answer

**Körd 2026-10-23** (commit `ea60f8da`), två live-repetitioner per arm, A3-kontrakt
och 40-parsbudget oförändrade.

| Arm | Generering | Prioritering | Rätt/26 | FS | Candidate Recall | Recall@40 | Unika konflikter | Jev | Väggtid |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | det | nuvarande | 16 | 6 | 8 | 6 | 5 | 2 320 | 160,6 s |
| B | hybrid | nuvarande | 22 | 0 | 14 | 12 | 9 | 2 336 | 185,7 s |
| C | det | metadata | 16 | 6 | 8 | 8 | 44 | 2 320 | 161,7 s |
| D | hybrid | metadata | **22** | **0** | **14** | **14** | **49** | 2 336 | 184,5 s |

**D är SSR-referens:** högst decision_correctness (delad med B), lägst
false-sufficient (0), coverage 22/22 och högst Recall@40 (14/14). Hybrid ger de
lågoverlappande kandidaterna; metadata lyfter `late_evidence` inom topp 40 i
båda repen. `late_evidence` slutar fortfarande `insufficient`, men det kända
paret väljs nu. Compatible-false-insufficient är oförändrad.

### Tidsuppdelning (två rep)

| Arm | Embedding | Generering | Prioritering | Jev-exekvering | Väggtid |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 0 | 239 ms | 0 | 1 103 547 ms | 160,6 s |
| B | 24 709 ms | 276 ms | 0 | 1 106 317 ms | 185,7 s |
| C | 0 | 257 ms | 297 ms | 1 133 817 ms | 161,7 s |
| D | 23 551 ms | 200 ms | 289 ms | 1 097 845 ms | 184,5 s |

Den ökade väggtiden (~15 %) är embeddingberäkning (~24 s för 500 texter i B/D),
inte generering eller metadata-prioritering; båda är under sekunden.
Jev-exekveringen dominerar i alla armar. Återanvändning av befintliga
Overgraph-embeddings tar bort merparten av overheaden.

**Beslut:** D är referens för SSR. Ingen produktionsändring; PR #426 orörd.
