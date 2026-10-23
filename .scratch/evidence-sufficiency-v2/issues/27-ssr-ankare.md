# Verifierade SSR-sakfrågeankare och utökat fryst facit

Type: task
Status: blocked
Blocked by: 38

## Question

Bygg förutsättningarna för ett meningsfullt SSR-experiment:

- Verifierade sakfråge-/klausulankare (inte tone/style) med versionerad
  mänsklig granskning.
- Utökat fryst facit med nya konfliktpar, inklusive fall som inte användes när
  ankarbiblioteket skapades, så att SSR kan visa nya träffar – inte bara fler
  kandidater.
- D (hybrid + metadata) är fortsatt referens; SSR får bara klassificera
  sakfrågor och hjälpa kandidatgenerering/prioritering, aldrig avgöra konflikter.
- Återanvänd facit v2-schemat; nya fall ska vara valid med planfråga, evidens,
  proveniens, förväntad relevans/relationer och motivering. Oberoende granskning
  krävs för tveksamma fall (inte samma Jev som testobjekt).
- Utöka med nya, tidigare osedda frågor och avtal innan resultaten används för
  generella slutsatser.
- Avgränsning: om SSR inte förbättrar Candidate Recall, tidig Recall@Budget
  eller kostnad mot D ska SSR inte in i evidensmotorn; den kan fortfarande
  användas för Tabular Review.

Ingen produktionsändring.

## Statuskontroll 2026-10-23 (före implementation)

- Befintlig SSR-ankarbibliotek finns i admin/backend: `ssr_anchor_sets`,
  pool-items och kalibrering, versionerat i Postgres (`api/anchor_sets.py`).
- Den är **tone/style**, inte sakfråga/klausul. Ingen `termination_notice`-
  kategoriaxel för research finns.
- Ingen Overgraph-persistens för ankare hittades i denna checkout; ingen
  Cursor-implementation av klausulankare finns heller.
- Därför byggs **inget parallellt SSR-system i experimentkoden**. Den
  gemensamma förmågan måste färdigställas först (ticket 34), med återanvändning
  av befintlig admin-/lagringsmekanism.
- Facit-QA v2b är klar (ticket 33) och v2-historiken är oförändrad.

Nästa: ticket 34, därefter detta ticket med ett litet verifierat ankarset mot D
på osedda avtal.
