# Blindtest v3 — resultat (en fryst körning)

**Status:** en körning på det frysta materialet och det frysta protokollet, inga
justeringar av promptar, M1–M6 eller komponenter. Båda kedjorna är bedömda mot **exakt
samma facit**. Material: `blindtest_v3_material.json`; fryst kedja:
`gliner2_chain_frozen_v2.json` (`gliner2-chain-m1m6-v1`).

## Armarna

- **M0** = fryst ursprungskedja (GLiNER2-kandidater → arm D/datum → E1–E3-kontraktet →
  single-value-utfall). Inga M1–M6.
- **M1–M6** = fryst kedja: M1-normalisering, M2-konsolidering, M3-rolltiebreak,
  M4-strukturkontext för PARTY, M6-selektiv återhämtning och M5-kardinalitet (UNKNOWN
  löses aldrig från värden enbart), sedan samma kontrakt.

Kedjan ser **endast GLiNER2-kandidater** (aldrig gold). Gold används enbart för
svarsnivåpoängsättning.

## Resultat

| Arm | Lösta | Korrekta svar | Korrekta avståenden | Felaktiga avståenden | Falskt RESOLVED | Överclaim (icke-besvarbara) | Evidenskontamination | Svarskontamination | Korrekt svar trots felaktig evidens | Exekvering JEV | Nya anrop |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M0 | 4/13 | 4 | 3 | 6 | 0 | 0 | 0 | 0 | 0 | 18 | 18 |
| **M1–M6** | **6/13** | **6** | **3** | **4** | 0 | 0 | 0 | 0 | 0 | **20** | 3 |

GLiNER2-inferenser: 13 (delade mellan armarna). Marginalnytta: **+2 korrekta svar**,
+2 lösta behov, **inga regressioner**, oförändrat antal korrekta avståenden.

## Per fall

| Fall | Dokument | Typ | Kard. | Besvarbar | M0 | M1–M6 | M0 D10 | M1–M6 D10 |
|---|---|---|---|---|---|---|---|---|
| v3-gbg-01 | Göteborg | PARTY | MULTIPLE_UNKNOWN | nej | unsolved | incomplete_unknown_cardinality | korrekt avstående | korrekt avstående |
| v3-gbg-02 | Göteborg | TERMINATION_CONDITION | SINGLE | ja | unsolved | unsolved | felaktigt avstående | felaktigt avstående |
| v3-gbg-03 | Göteborg | PERIOD | SINGLE | nej | unsolved | unsolved | korrekt avstående | korrekt avstående |
| v3-lst-01 | Länsstyrelsen | PARTY | MULTIPLE_UNKNOWN | nej | unsolved | incomplete_unknown_cardinality | korrekt avstående | korrekt avstående |
| v3-lst-02 | Länsstyrelsen | PERIOD | SINGLE | ja | unsolved | unsolved | felaktigt avstående | felaktigt avstående |
| v3-lst-03 | Länsstyrelsen | PERIOD | SINGLE | ja | unsolved | resolved | felaktigt avstående | **korrekt svar** |
| v3-lst-04 | Länsstyrelsen | NOTICE_PERIOD | SINGLE | ja | resolved | resolved | korrekt svar | korrekt svar |
| v3-lst-05 | Länsstyrelsen | PERIOD | SINGLE | ja | resolved | resolved | korrekt svar | korrekt svar |
| v3-lst-06 | Länsstyrelsen | TERMINATION_CONDITION | SINGLE | ja | unsolved | unsolved | felaktigt avstående | felaktigt avstående |
| v3-nac-01 | Nacka | LIABILITY_CAP | SINGLE | ja | unsolved | unsolved | felaktigt avstående | felaktigt avstående |
| v3-nac-02 | Nacka | PERIOD | SINGLE | ja | unsolved | resolved | felaktigt avstående | **korrekt svar** |
| v3-nac-03 | Nacka | NOTICE_PERIOD | SINGLE | ja | resolved | resolved | korrekt svar | korrekt svar |
| v3-nac-04 | Nacka | NOTICE_PERIOD | SINGLE | ja | resolved | resolved | korrekt svar | korrekt svar |

**Vinster:** `v3-lst-03` (betalningsfrist) och `v3-nac-02` (kravfrist) — båda via **M6:s
selektiva återhämtning**: första bedömningen svarade `NO`, deterministisk detektor och
rollmatchning motiverade exakt en kompletterande bedömning, som svarade `YES`, och värdet
matchar gold. M1–M5 hade ingen observerbar effekt på dessa klausuler.
**Regressioner:** inga.

## D10 — evidens vs slutsats

| Mått | M0 | M1–M6 |
|---|---|---|
| Evidenskontamination (verifierat värde utanför förväntad mängd) | 0 | 0 |
| Svarskontamination (slutligt svar innehåller felaktigt värde) | 0 | 0 |
| Falskt RESOLVED / överclaim på icke-besvarbara behov | 0 | 0 |
| Korrekt svar trots felaktig evidens | 0 | 0 |
| Korrekta avståenden (icke-besvarbara) | 3/3 | 3/3 |

Ingen arm verifierade ett värde utanför den förväntade mängden, och ingen arm avgav ett
felaktigt svar. Skillnaden mellan evidens och slutsats var därför inte utmanad i denna
körning — men måtten redovisas separat och var noll även för den förbättrade kedjan.

### UNKNOWN-kardinalitet

`v3-gbg-01` och `v3-lst-01` är flervärdesbehov där fullständig partlista inte kan
fastställas. **M0 lämnade båda olösta** (korrekt avstående), och **M1–M6 tvingade
`incomplete_unknown_cardinality`** enligt M5-policyn. Ingen överclaim i någon arm. Policyn
fungerade alltså som skydd, men var **inte diskriminerande** i dessa fall: M0 avstod av
andra skäl. Ett starkare test krävs där en ofullständig delmängd annars skulle ha löst
behovet.

## Vad som fortfarande saknas

Fyra besvarbara behov förblev olösta i båda armarna:

- `v3-gbg-02`, `v3-nac-01`: **inga GLiNER2-kandidater** — kandidatgenereringslucka.
- `v3-lst-02`, `v3-lst-06`: kandidater finns men behovet löses inte — första
  verifieringen/kandidatkvaliteten.

Absolut korrekthet är 6/13. Det är blygsamt och domineras av kandidatgenerering, inte av
M1–M6. Att jaga det med fler verifieringsförsök vore fel.

## Kostnad

- M0: 18 exekveringar, 18 nya JEV-anrop.
- M1–M6: 20 exekveringar, 3 nya anrop (resten replay ur fryst v3-fixtur); +2 anrop
  (+11 %) för +2 korrekta svar. 13 GLiNER2-inferenser delade.

## Slutsats

**Delvis stöd för generalisering:** M6:s selektiva återhämtning överförs till nya
dokumenttyper (+2 korrekta svar, inga regressioner, ingen kontamination). Men hela
M1–M6-kedjan visar måttlig absolut korrekthet (6/13), och M1–M5 gav ingen observerbar
vinst på dessa dokument. Underlaget räcker **inte** för bred aktivering i Investigation.

Två rimliga nästa steg (beslut efter denna rapport):

1. **Större oberoende blindtest** med fler besvarbara klausuler och konstruerade fall där
   en ofullständig delmängd annars skulle lösa ett UNKNOWN-behov (för att bevisa
   M5-skyddet), samt fler kandidatgenereringsfall.
2. **Begränsad Investigation-pilot** med M6 (den enda uppmätta överförbara förbättringen)
   under fortsatt utvärdering — inte hela M1–M6.

## Reservation

En fryst körning, 13 behov, publika upphandlings-/avtalsdokument. Resultatet är evidens,
inte en produktionsgaranti. Inga justeringar gjordes efter att körningen började.
Artifakterna i repot är redigerade (ids, typer, kardinalitet, klasser, counts, hashar).
