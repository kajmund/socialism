# 37 – Adminflöde för verifiering och aktivering

Type: task
Status: resolved
Blocked by: 35

## Question

Bygg det vertikala adminflödet ovanpå befintlig SSR-admin:

- Välj klausul, svara Ja/Nej/Osäker, spara källa/provenance.
- Separat aktiveringssteg med tydlig status; endast verifierade ja-ankare.
- Lista över väntande/aktiva/återkallade verifieringar.
- Återanvänd i18n, adminlayout och befintliga API-mönster; ingen ny parallell
  SSR-vy.

Leverans: fungerande UI-flöde + tester.

## Status 2026-10-23

Täcks av PR #428 (`/clause-ssr` admin Ja/Nej-kö, undo, promotion, anchor sets). Granska/rebase i stället för att bygga nytt.

## Avslut 2026-10-23

Levererad via PR #428: admin Ja/Nej-kö, undo, promotion och anchor sets.
