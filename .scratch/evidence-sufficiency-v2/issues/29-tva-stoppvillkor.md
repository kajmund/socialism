# Två stoppvillkor: fastställd konflikt vs full konfliktkartläggning

Type: grilling
Status: resolved
Blocked by: 28

## Question

Ska SWE kunna avsluta med "evidensen är konfliktfylld" efter ett verifierat
avgörande konfliktpar, medan "kartlägg alla relevanta konflikter" kräver full
täckning?

- Gör uppdragen explicita i workflowets mål; de får olika stoppvillkor.
- Fastställd konflikt kan ibland räcka efter ett verifierat par; full
  kartläggning kräver coverage.
- Mät Jev-anrop och beslutskvalitet för respektive mål; ändra inte
  beslutssemantiken utan eget test.
- Påverka inte coverage-diagnostiken negativt.

Ingen produktionsändring.

## Answer

**Steg 1 (shadow) körd 2026-10-23** i commit `0b469d93`. Ingen exekveringsändring;
produktionsbeteendet är kvar.

Rapporten exponerar `stop_shadow` för målet `conflict_confirmed`: första
parbedömning med `CONTRADICTS` som är en olöst konflikt med verifierad relevans,
samt kvarvarande par-anrop, uppskattad sparad tid, coverage-status och riskflagga.

Live-shadow (D-konfiguration, 8 fall × 2 rep):

| Mått | Resultat |
| --- | ---: |
| Möjliga stopp | 12 / 16 fall-körningar |
| Uppskattade sparade Jev-anrop | 165 |
| Uppskattad sparad par-latens | 44,6 s |
| Stopp med komplett coverage | 8 |
| Stopp med ofullständig coverage | 4 (`late_evidence`, `tail_claim_contradiction`) |

Konfliktparet var identiskt i båda repetitionerna för varje stoppat fall, och
inget stopp byggde på en konflikt som senare löstes. För målet "är evidensen
konfliktfylld?" är de fyra ofullständiga stoppen acceptabla om resultatet
märks som ofullständigt; för "kartlägg alla konflikter" måste arbetet fortsätta.

**Steg 2** är en separat experimentarm där tidigt stopp faktiskt tillåts
(ticket 30). Där mäts sparade Jev-anrop, latens, false-sufficient och om något
stopp bygger på en konflikt som senare visar sig felaktig/irrelevant.
