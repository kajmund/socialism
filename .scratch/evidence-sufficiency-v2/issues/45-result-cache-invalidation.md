# 45 – Resultatcache-invalidering och revocation-paritet

Type: task
Status: open
Blocked by: 44

## Question

Gör C-armens Top-K-resultat till en korrekt cache i stället för ett blindt
återanvänt tabellresultat.

- Resultatnyckel: dokumentversion/content hash, embeddingmodell, AnchorSet-id +
  revision/medlemskap, kategori/label, polaritet, tröskel, kandidatgräns och
  algoritmversion.
- Vid ändrad nyckel: räkna om; vid oförändrad: återanvänd Top-K.
- Revocation: matcha → godkänn → lås → återkalla → matcha. Nya matchningar får
  aldrig använda återkallade ankare; låsta celler behåller historik men får inte
  presenteras som aktuellt SSR-stöd.
- Testa både varm cache och cachemiss.
- Testa processomstart, två workers, AnchorSet-ändring, dokumentuppdatering och
  eventuell eviction; lokala cachemissar får kosta ~1 s men ge korrekt resultat.
- Ingen ny Redis/SQL/vektordatabas; Overgraph behåller embeddings/ankare,
  granskningsbeslut/lås persisteras separat.

Därefter kan C/D-beslut fattas; quality claims väntar fortfarande på ticket 41/43.
