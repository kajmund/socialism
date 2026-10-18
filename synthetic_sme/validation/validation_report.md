# Valideringsrapport – SPEC Synthetic SME Benchmark v1.0

PASS: 16 | FAIL: 0 | NOT_TESTED: 0 | Totalt: 16

## 1. Varje verifikation balanserar – PASS
  - Alla 3637 verifikationer balanserar (summa 0,00).
## 2. Ingående och utgående saldon är konsekventa (SIE-korsavstämning) – PASS
  - UB 0 i FY2025-filen == IB 0 i FY2026-filen för samtliga konton.
## 3. Balansräkningen balanserar – PASS
  - Totalsumma alla konton = 0,00 (balans).
## 4. Kundreskontra överensstämmer med huvudboken (1510) – PASS
  - 1510 = 6981670.00 = öppna kundfordringar 6981670.00.
## 5. Leverantörsreskontra överensstämmer med huvudboken (2440) – PASS
  - 2440 = -1203980.63 = öppna leverantörsskulder 1203980.63.
## 6. Banktransaktioner kan avstämmas mot huvudboken (1930) – PASS
  - 1930 = 9436780.73 = banktransaktioner 9436780.73.
## 7. Fakturor refererar till giltiga kunder och avtal – PASS
  - 889 kundfakturor har giltiga kund-/avtalsreferenser.
## 8. Avtalspriser och fakturering stämmer (med dokumenterade avvikelser) – PASS
  - Alla löpande fakturor matchar timmar × pris; avvikelser är de dokumenterade händelserna.
## 9. Lönekostnader och löneunderlag stämmer – PASS
  - 7210 = 40941000.00 = löneunderlag 40941000.00.
## 10. Projektkostnader och intäkter har korrekt koppling – PASS
  - Alla faktura- och schemareferenser pekar på befintliga projekt.
## 11. Dokument- och entitetsreferenser är giltiga – PASS
  - 377 dokument registrerade; händelsereferenser och författare giltiga.
## 12. 200 unika Golden Questions finns – PASS
  - 200 unika fråge-ID:n (GQ-001..GQ-200).
## 13. Varje besvarbar fråga har verifierbart facit – PASS
  - Facit finns för alla 171 besvarbara frågor.
## 14. Frågor med otillräckligt underlag är korrekt markerade – PASS
  - Alla 8 INSUFFICIENT_EVIDENCE-frågor är markerade i täckningsmatrisen.
## 15. Inga facitdata läcker in i ingestpaketet – PASS
  - Inga facitmarkörer i ingestfiler.
## 16. SIE-filerna kan läsas tillbaka utan förlust – PASS
  - Båda SIE4-filerna läses tillbaka: SIETYP 4, PC8, balanserade verifikationer, saldon matchar GL.