# B3 – Adaptivt urval av faktapar efter informationsvärde

Type: grilling
Status: resolved
Blocked by: –

## Question

Kan SWE välja **vilka** faktapar som Jev får jämföra, i stället för att bara
fylla en fast 40-parsbudget — och ge samma eller bättre beslut med färre
Jev-anrop?

Detta är det sannolikt viktigaste SWE-experimentet: A3 visar att Jev hittar
motsägelser när rätt par jämförs, men den fasta budgeten lämnar relevanta
jämförelser ogjorda (`late_evidence`).

## Pre-registrering (lås före körning)

- **Urvalsfeatures:** källoberoende, motsatt polaritet, överlappande sakfråga,
  tidigare oprövad relation, täckning av öppna need-frågor. Ingen facit-läckage.
- **Budget:** taket ligger kvar; taket får inte ensamt avgöra urvalet.
- **Kontrakt:** samma verifierbara A3-beslutskontrakt (Jev-bedömning, A2-
  konfliktmodell, coverage-gate). Endast urvalsordningen ändras.
- **Jämförelsearmar:** A3 fast deterministisk ordning vs B3 informationsvärde
  (deterministisk score först; embedding-baserad prioritering endast om den
  deterministiska inte räcker).
- **Mått:** contradiction_detection, evidence_coverage, decision_correctness,
  false-sufficient, false-insufficient, Jev-anrop per korrekt beslut och
  cost_per_detected_contradiction.
- **Beslutskriterium:** samma eller bättre besluts kvalitet än A3 med färre
  Jev-anrop; annars behåll A3:s ordning. Höj inte 40-parsbudgeten för gröna
  siffror.

## Leverans

Artefakt med armjämförelse på de låsta fallen + tidigare osedda fall, samt
PASS/FAIL mot kriterierna. Ingen produktionsändring; PR #426 orörd.

## Låst protokoll före körning (2026-10-23)

**Prioriteringsgränssnitt:** rena rankningar över befintlig kandidatmängd.
`prioritize_pairs(candidates, claims, ordering=...)` returnerar en ordnad lista;
SWE behåller budgettak, Jev-exekvering och A3:s beslutskontrakt. En senare
SSR-scorer ska kunna läggas till som en ny ordering utan att exekveringslogiken
ändras.

**Armar i denna körning:**

- **B3-A** nuvarande ordning (deterministisk kandidatordning).
- **B3-B** deterministisk metadata-prioritering: entitet/definition, frågeoverlapp,
  källoberoende, polaritets-/värdeskillnad, canonical-downweight, ej prövad relation.
- **B3-C** metadata + redan existerande embeddings (proxy). SSR-ankare är **inte**
  en del av B3-C; de kräver verifierade ankare och läggs som separat arm senare.

Inga nya modellanrop för urvalet. Jev anropas först efter att SWE valt par.
Budgeten 40 ligger kvar.

**Primärt mått:** Recall@Budget-kurva för k = 1, 5, 10, 20, 40 mot kända
motsägelsepar i pair-gold (positiva fall: duplicate, independent,
tail_claim). Final decision_correctness, evidence_coverage och
false-sufficient mäts separat i nästa steg.

**Beslutskriterium:** B3 får ersätta A3:s ordning endast om den når samma eller
bättre recall vid mindre eller lika budget, utan att öka falska positiva i
slutbedömningen. Om B3-B/C inte slår B3-A behålls nuvarande ordning. Höj inte
40-parsbudgeten.

**SSR-arm (senare):** [ticket 19](19-b3-ssr-arm.md) får endast köras när
tillräckligt många verifierade SSR-ankare finns; den återanvänder samma
prioriteringsgränssnitt och jämförs separat mot B3-B/C.

## Answer

**Första B3-körningen 2026-10-23** i commit `f2e4580f`. Prioriteringsgränssnittet
är implementerat (`prioritize_pairs`), A3:s beslutskontrakt och 40-parsbudgeten
är oförändrade, och urvalet gör inga modellanrop.

Armar: A nuvarande ordning, B deterministisk metadata-prioritering, C metadata +
befintliga embeddings (proxy, **inte** SSR). SSR-armen skjuts till ticket 19.

Recall@Budget på pair-golds tre positiva fall (duplicate, independent,
tail_claim):

| Arm | @1 | @5 | @10 | @20 | @40 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A nuvarande | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| B metadata | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| C embeddings-proxy | 0.67 | 0.67 | 0.67 | 0.67 | 1.00 |

**Resultatet är ett tak, inte ett bevis på att nuvarande ordning är optimal.**
De kända motsägelserna i pair-gold ligger redan på rank 1; C trycker ner
`tail_claim_contradiction` till rank 31. `late_evidence` och `large_567k` saknar
fryst par-facit, så kurvan kan inte visa den verkliga vinsten.

**Beslut:** behåll nuvarande ordning tills vidare. B3 får inte bytas in på ett
ceiling-resultat. B3b (ticket 20) måste lägga till verifierade lågrankade
motsägelsepar, särskilt late/large, och därefter mäta decision_correctness och
coverage separat innan någon ordning ändras.

Kostnad: 0 Jev-anrop; embeddingsanrop för C redovisas i artefakten.
