# Blindtest v2 — ablationsarm M5: flervärdesbehov (eget experiment)

**Status:** diagnostisk utvecklingskörning på det frysta blindtest v2-materialet.
M0 fryst; M1–M4 (PR #451/#452) oförändrade. M5 ändrar **vad ett löst behov betyder**,
inte hur evidens verifieras. M6 (verifieringsåterhämtning) hålls medvetet separat.

## Design

Kardinalitet är en **behovsegenskap**, inte ett specialfall för avtalsparter — samma
semantik ska kunna användas för samtliga undantag, alla ansvariga parter, flera
konkurrerande avtalsvillkor och flera rättskällor.

| Arm | Innehåll |
|---|---|
| **M0** | fryst referens (single-value-kontraktet) |
| **M5** | enbart kardinalitetsmodellen |
| **M12+M3+M4** | ackumulerat M1–M4, fortfarande single-value |
| **M12+M3+M4+M5** | ackumulerat + kardinalitetsmodellen |

### Kardinalitetspolicy

| Kardinalitet | Resolved när |
|---|---|
| **SINGLE** | oförändrat fryst kontrakt |
| **MULTIPLE** (känt `expected_count`) | **alla** förväntade värden verifierade, **inga** värden utanför den förväntade mängden verifierade, och antalet matchar |
| **UNKNOWN** | aldrig enbart från värden — kräver ett **fullständighetsresultat** |

- `expected_count` kommer från den oberoende facit-annoteringen, **aldrig** från antalet
  verifierade kandidater.
- **"Hittat" ≠ "fullständigt":** hittade men ofullständiga behov får en explicit
  `partial`-status; de räknas aldrig som lösta.
- Verifierade värden utanför den förväntade mängden ger `ambiguous_extra` (aldrig
  resolved) — samma princip som falskt-RESOLVED-skyddet.
- `UNKNOWN`-policyn är implementerad och konformanstestad syntetiskt; inget v2-fall har
  okänd kardinalitet, så den måste valideras på det nya osedda testsetet.

## Resultat

| Arm | Lösta | PARTIAL | Falskt RESOLVED | Kontamination | Exekvering JEV | Nya anrop |
|---|---|---|---|---|---|---|
| M0 | 7/16 | 0 | 0 | 0 | 32 | 0 |
| **M5** | **8/16** | **1** | 0 | 0 | 32 | 0 |
| M12+M3+M4 | 13/16 | 0 | 0 | 0 | 26 | 0 |
| **M12+M3+M4+M5** | **14/16** | **1** | 0 | 0 | **26** | 0 |

### Flervärdesfallen (explicit hittat vs fullständigt)

| Fall | Kardinalitet | Hittade | Saknas | Extra | M0 | M5 |
|---|---|---|---|---|---|---|
| v2-sv-01 | MULTIPLE, 3 | 3 | 0 | 0 | ambiguous | **resolved** |
| v2-pm-07 | MULTIPLE, 2 | 1 | 1 | 0 | unsolved | **partial** |

`v2-pm-07` blir alltså **inte** resolved av M5: en av två parter verifieras fortfarande
inte. Det är den explicita skillnaden mellan "jag har hittat en part" och "jag har hittat
samtliga parter" — och skälet att M6 behövs separat.

### Oförändrade single-value-behov

Instrumentet assertar att M5 **inte** ändrar något single-value-behov: 0 ändrade fall i
både `M5` mot `M0` och `M12+M3+M4+M5` mot `M12+M3+M4`.

### Policyns konformanstester (syntetiska, inga avtalsdata)

| Test | Resultat |
|---|---|
| MULTIPLE med alla förväntade → resolved | ✅ |
| MULTIPLE med saknat värde → partial (ej resolved) | ✅ |
| MULTIPLE med extra värde → ambiguous_extra (ej resolved) | ✅ |
| UNKNOWN löses aldrig enbart från värden | ✅ |
| SINGLE behåller fryst utfall | ✅ |

## Ekonomi

M5 ändrar ingen verifiering: **0 nya JEV-anrop, 0 nya inferenser**. Exekveringskostnaden
är oförändrad (M5 32, ackumulerat 26 — 6 färre än M0 tack vare M2). Ackumulerat ger
**14/16** med 26 JEV-anrop mot M0:s 32.

## Slutsatser

1. **M5 löser det enda behov som enbart blockerades av kardinalitet** (`v2-sv-01`) och
   gör `v2-pm-07` explicit ofullständigt i stället för att gissa — utan nya anrop och
   utan att röra single-value-behoven.
2. **Kardinalitet är nu en generell behovsegenskap**, inte en parts-speciallösning.
3. **Kvarvarande:** `v2-pm-05` (verifiering) och `v2-pm-07` (verifiering; partial) —
   båda pekar på M6, som ska köras som eget experiment. Ingen bredare aktivering från
   dessa 16 diagnostiska fall.

## Reservation

De 16 fallen är en diagnostisk utvecklingsmängd. Ett nytt, osynligt dokumenttest krävs
innan bredare aktivering. Frysta artefakter från #450–#452 är oförändrade.
