# Golden-facit QA och versionerat facit

Type: task
Status: resolved
Blocked by: 30

## Question

Gör golden-facit till förstklassig testinfrastruktur så att ett felaktigt facit
inte får oss att optimera bort ett korrekt säkerhetsbeteende.

- Varje golden-fall ska innehålla: planfråga, förväntat beslut, evidens och
  källproveniens, förväntad relevans för planfrågan, förväntade semantiska
  relationer och motivering till facit.
- Automatisk varning när ett facit förutsätter att off-topic-evidens ska räcka
  för `sufficient`. Kontrollen får kombinera deterministiska regler med separat,
  oberoende granskning — men aldrig använda exakt samma Jev-bedömning som både
  facit och testobjekt.
- Versionera facit; behåll historiska resultat orörda. Kör en ny utvärdering av
  D mot det korrigerade facit (potentiellt 26/26) i stället för att skriva om
  B4c.
- Dokumentera processen i testinfrastrukturen.

Ingen produktionsändring.

## Answer

**Implementerad 2026-10-23** i commit `ee4a0867`. Historiska resultat är orörda.

- `golden-facit-v2.json` med per fall: planfråga, förväntat beslut, evidens
  (excerpt/status/provenance), förväntad relevans, förväntade semantiska
  relationer, motivering och granskningsmetadata.
- Status `valid` / `invalid` / `diagnostic`; ogiltiga fall kräver orsak,
  diagnostiska fall exkluderas från accuracy.
- Deterministisk QA (`facit_qa.py`) avvisar valid sufficient när relevant
  evidens saknar lexikal relation till planfrågan, avvisar Jev-baserad
  granskning och saknad motivering, samt varnar för väntande oberoende
  granskning.
- Gamla `compatible_periods`/`compatible_entities` är **invalid** för 36 §-
  frågan (off-topic-evidens); on-topic-ersättarna är valid men har
  `independent_review_required` kvar som varning. `large_567k` är diagnostic.

Artefakter: `golden-facit-v2.json`, `facit-qa-v1.json`,
`facit-v2-d-evaluation.json`.

**Ny D-körning mot v2:** 20 valida fall × 2 rep = **40/40 korrekta**, 0
false-sufficient, 0 false-insufficient. Detta är ett litet, välkänt
testmaterial — inte bevis på generell beslutskvalitet. Nya, osedda frågor och
avtal krävs innan produktionspåståenden.

Kvar: oberoende mänsklig granskning av de nya on-topic-fallen och ett utökat
fryst testmaterial. Nästa är ticket 27 (SSR-förutsättningar), därefter adaptiv
parallellism (ticket 32).
