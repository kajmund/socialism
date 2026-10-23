# Gemensam SSR-ankarbibliotek för sakfrågor

Type: task
Status: resolved
Blocked by: –

## Question

Färdigställ den gemensamma förmågan som research/SSR-experimentet ska återanvända,
i stället för att bygga ett parallellt system i experimentkoden:

- Utöka befintlig `ssr_anchor_sets`/pool till **sakfrågeklausuler** (t.ex.
  `termination_notice`) med positiva/negativa/oklara ankare, inte bara
  tone/style.
- Mänsklig verifiering i admin: Ja / Nej / Osäker, med källa och provenance.
- Versionerade ankare med verifieringsstatus, kategori, polaritet och embedding;
  persistens i den gemensamma kunskaps-/Overgraph-vägen (eller dokumenterad
  motsvarande gemensam mekanism).
- Återanvänd admin-CRUD, kalibrering och API; ingen ny parallell SSR-runner.
- Leverera ett litet men korrekt verifierat ankarset för experimentet, utan att
  testavtal förekommer i biblioteket.
- Tester för verifieringsflöde, versionering, persistens och avstående
  (klausul utan kategori).

När detta fungerar kan ticket 27 köras mot D på osedda avtal. Ingen
produktionsändring av evidensmotorn.

## Investigation (2026-10-23)

- Existing: `ssr_anchor_sets`, `ssr_anchor_pool_items`,
  `ssr_anchor_calibration_items`, publish/calibration gates, admin SSR page.
  Kinds are `tone|style` only; no topic/clause kind.
- Overgraph has knowledge write/read, but **no anchor index or sync**.
- No Cursor clause-anchor/Overgraph implementation found in this checkout,
  remote branches or worktrees. The Slack thread is not accessible here; check
  any Cursor branch/commit before coding to avoid duplicate work.
- Decision: extend the existing library; do not build a parallel SSR system.
  Postgres owns verification, Overgraph owns the searchable index.
- Plan: [ssr-anchor-library-extension.md](../../docs/architecture/ssr-anchor-library-extension.md).
- Split into tickets 35 (schema/verification API), 36 (Overgraph index/sync),
  37 (admin vertical flow), 38 (matching/experiment); ticket 27 waits for 38.

Implementationsuppdelning: ticket 35 (verifiering/schema), 36 (Overgraph-index),
37 (adminflöde), 38 (matchning/experiment). Ticket 34 är paraply och stängs när
den vertikala acceptansen i 38 är uppfylld.

## PR-granskning 2026-10-23

Verifierad status: #428 OPEN/MERGEABLE med grön CI; #429 OPEN/MERGEABLE med 12
gröna kontroller. Båda är hämtade som `review/pr-428` och `review/pr-429`.

**Fynd:** PR #429 har ingen dependency till #428. #428 bygger ett isolerat
Overgraph-klausulbibliotek med verifieringskö/promotion/match; #429 lägger
`kind="clause"` på befintliga SQL-`ssr_anchor_sets` och använder dem för Tabular
Review. Det ger två konkurrerande klausulbibliotek — precis den dubblering
ticket 34 skulle förhindra.

**Rekommendation:** Adoptera #428 som enda klausulsubsystem (Overgraph
auktoritativt för klausuler; Postgres behåller tone/style). Omerbeta #429 ovanpå
#428 så att clause-kolumner använder samma tjänst; ta bort SQL-vägen
`kind="clause"`. Merga #428 först, rebasa #429, kör om tester, merga sedan.
Tickets 35–37 startas inte som ny implementation; de täcks av #428.

Detaljer: `docs/architecture/ssr-clause-pr-review.md`.

## Kodgranskning av #428 2026-10-23

- Verifiering/aktivering separerade: ja.
- Negativa ankare kategorispecifika: ja i koden; komplettera med explicit
  cross-category-test.
- Återkallelse: **blockerande fel**. `revoke_verification` samt byte av svar
  (yes→no) återkallar inte redan promoverade ankare; gamla anchor sets kan
  fortsätta matcha. Kräver fix i #428 före merge: återkalla alla ankare med
  `verification_id`, testa undo/answer-change med promoverat ankare + aktivt set.
- #428 använder SQL endast för `UserAccount`-auth, inte för klausuldata: ja.
- Slutsats: #428 får inte mergas förrän revokeringens kaskad är fixad. Därefter
  #429/ticket39, sedan 38 och 27.

## Avslut 2026-10-23

PR #428 är mergad som `77b8ded8` efter fix `ca68ad0d`. Revokeringskaskaden,
read-guarden och testerna är gröna; CI grönt. Overgraph är därmed enda
persistens-/sökmotor för klausuldomänen. Kvarvarande arbete är att omerbeta
PR #429 (ticket 39) så Tabular Review konsumerar samma tjänst; därefter 38/27.
