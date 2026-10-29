# 35 – SSR-verifiering och schema (Postgres auktoritativ)

Type: task
Status: resolved
Blocked by: –

## Question

Utöka den befintliga SSR-ankarmodellen med kind-medveten verifiering:

- Tillåt ankarsettyperna `document_type`, `clause_category`, `clause_variant`,
  `question_intent` utöver `tone`/`style`; samma lagring/versionering.
- Ny Postgres-tabell för verifieringsbeslut: ankarset/version, kategori,
  klausultext, verdict `yes|no|unsure`, källa/provenance, verifierad av/när,
  aktiveringsstatus.
- API för att skapa/läsa/återkalla verifiering samt separat aktiveringssteg;
  endast `yes` får aktiveras.
- Kind-medveten payload-validering; återanvänd befintlig admin-CRUD/API.
- Tester för verifiering, återkallning, aktivering, otillåten aktivering och
  att tone/style fungerar oförändrat.

Ingen Overgraph-indexering i denna ticket; det är ticket 36. Ingen
produktionsändring av evidensmotorn.

## Status 2026-10-23

Täcks av PR #428 (verifieringskö, revisioner, explicit promotion). Starta inte som ny implementation; invänta granskning/merge av #428. Ticket 38 ansvarar för D-jämförelsen efter merge.

## Avslut 2026-10-23

Levererad via PR #428 (mergad `77b8ded8`): verifieringskö, revisioner, explicit promotion, read-guard och tester. Ingen separat implementation behövs.
