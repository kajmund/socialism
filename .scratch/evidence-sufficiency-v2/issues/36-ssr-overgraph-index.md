# 36 – Overgraph-ankarin­dex och idempotent synk

Type: task
Status: resolved
Blocked by: 35

## Question

Bygg det sökbara ankarindexet i Overgraph:

- Aktiva verifierade ankare blir noder med kategori, polaritet, embedding,
  modellversion och relation till källa/TextUnit.
- Idempotent synk från Postgres (create/revoke/version bump); synkad revision
  spåras, fel är synliga och tyst fallback är förbjuden.
- Endast aktiva verifierade ankare får matchas; återkallad verifiering
  inaktiverar och tar bort från indexet.
- Hantera blandade embeddingmodellversioner fail-loud.
- Tester för synk, idempotens, revoke och modellversion.

Ingen ny parallell SSR-runner; återanvänd befintliga Overgraph-skrivningar.

## Status 2026-10-23

Täcks av PR #428 (Overgraph-noder, lagrade TextUnit-vektorer, aktivt anchor set, modellversion/revoke). Ingen separat Postgres→Overgraph-synk behövs om #428 antas; arkitekturbeslut i ticket 34.

## Avslut 2026-10-23

Levererad via PR #428: Overgraph-noder, lagrade TextUnit-vektorer, aktiva sets, modellversion/revoke och matchnings-API. Ingen Postgres-synk.
