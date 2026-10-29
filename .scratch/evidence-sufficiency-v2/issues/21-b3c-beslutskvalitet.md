# B3c – Fullt live-arm med metadata-ordning

Type: grilling
Status: resolved
Blocked by: 20

## Question

Förbättrar B3-B metadata-ordning den **slutliga** beslutskvaliteten — inte bara
Recall@Budget — utan att false-sufficient, coverage eller Jev-kostnad försämras?

- Kör A (nuvarande ordning) och B (metadata) som fulla live-armar på de låsta
  fallen, två repetitioner, samma A3-kontrakt och 40-parsbudget.
- Repetera direkt Jev-bedömning av `duplicate_contradiction`-facitparet för att
  avgöra om SCOPE_DIFFERENCE var tillfälligt eller systematiskt.
- Mät: decision_correctness, false-sufficient, false-insufficient,
  evidence_coverage, contradiction_detection, Jev-anrop per korrekt beslut,
  Recall@Budget och kostnad.
- Förregistrerat adoptionskriterium: B3-B får ersätta nuvarande ordning endast
  om decision_correctness är minst lika bra, false-sufficient inte ökar,
  coverage inte försämras och Jev-anropen inte ökar. Annars behåll A3.
- Ingen produktionsändring; PR #426 orörd.

Leverans: armartefakt + PASS/FAIL-tabell och adoptionsbeslut.

## Answer

**Körd 2026-10-23** (commit `52bb0725`), två live-repetitioner per arm, A3-kontrakt
och 40-parsbudget oförändrade.

| Mått | A nuvarande | B metadata |
| --- | ---: | ---: |
| Rätt / 22 | 16 | 16 |
| False-sufficient | 2 | 2 |
| False-insufficient | 4 | 4 |
| Coverage complete | 18 | 18 |
| Falska konflikter | 0 | 0 |
| Jev-anrop | 2 308 | 2 308 |
| Latens | 159 s | 159 s |

Informationsvärde per Jev-anrop (separat mätning):

| Utfall | A | B |
| --- | ---: | ---: |
| Ny relevant motsägelse | 4 | **44** |
| Ny verifierad förenlighet | 81 | 41 |
| Upprepad känd relation | 85 | 85 |
| Felaktig semantisk bedömning | 0 | 0 |

- `late_evidence` är `insufficient` i båda armarna, men A failar closed på
  ofullständig coverage utan att hitta paret; B hittar 40 motsägelser inklusive
  det kända sena paret. Slutbedömningen ändras inte eftersom coverage redan
  blockerade.
- `duplicate_contradiction` gav CONTRADICTS i båda repetitionerna i båda armarna
  — den tidigare SCOPE_DIFFERENCE var tillfällig.
- De förregistrerade icke-inferioritetskriterierna passerar, men **bättre
  slutlig beslutskvalitet är inte visad**. B flyttar anrop från förenlighet till
  motsägelsedetektion till samma kostnad.

**Beslut:** behåll nuvarande produktionsordning. B3-B registreras som
detektionsförbättrande kandidat, inte som ny standard. Ingen produktionsändring.

Nästa spår: kandidatgenerering för synonymfall (ticket 22) och SSR-baserad
sakfrågeklassificering (ticket 19), separat från generell embedding-ranking.
