# Blindtest v2 — ablationsarmar M3 (rollrobusthet) och M4 (behovsanpassat kontext)

**Status:** diagnostisk utvecklingskörning på det frysta blindtest v2-materialet.
M0 är oförändrad fryst referens; #451 (M1/M2) är orörd. Inga modeller körs; inga
avtalsdata committas (artefakterna innehåller case-id, typer, utfall, roller, hashar,
offset och antal).

## Design

| Arm | Innehåll |
|---|---|
| **M0** | fryst kedja, referens (7/16) |
| **M3** | rollrobusthet: deklarerad behovsroll får bryta en rolltie **endast** när behovsrollens cue finns i spannets mening |
| **M4** | behovsanpassat, strukturstyrt kontextfönster för PARTY-behov |
| **M34** | M3 + M4 |
| **M12+M3+M4** | ackumulerat: M1 + M2 + M3 + M4 |

### M3 — regel (generell, konservativ)

Om närmaste-kue-rollen är bestämbar men skiljer sig från behovets deklarerade roll,
**och** en cue för den deklarerade rollen finns i samma mening som spannet, används den
deklarerade rollen. Saknas cue:n står klassificerarens roll kvar. Det är en tie-break,
inte en override: pm-03 (MONEY mot LIABILITY/MONEY i samma mening) påverkas inte, eftersom
rollen redan matchar behovet.

Tie-break-cue-matchningen tillåter vanliga svenska böjningsändelser
(`uppsägningstid` → `uppsägningstiden`) — bara i M3:s tie-break, aldrig i det frysta
kontraktets klassificerare.

### M4 — regel (behovsanpassad, strukturell)

Endast PARTY-behov får ett bredare fönster. Fönstret är det **strukturella block** som
innehåller spannet: maximalt 8 rader per riktning, stopp vid tom rad, sidmarkör
(`Sida N`, sidnummer) eller rubrikrad, och rubrikraden ovanför inkluderas. Det är aldrig
ett godtyckligt teckenantal. Ickepartbehov behåller klausulen som kontext (oförändrat).

**Fixturidentitet:** varje M4-svar nycklas av **hela bedömningsuppgiften** — case-id,
spann-digest, promptversion och SHA-256 av den exakta kontexttexten. Ett JEV-svar från
kort kontext återanvänds aldrig för en längre kontext.

## Resultat

| Arm | Lösta | Δ mot M0 | Falskt RESOLVED | AMBIGUOUS | Exekvering JEV | Experiment nya anrop |
|---|---|---|---|---|---|---|
| M0 | 7/16 | — | 0 | pm-03, sv-01 | 32 | 0 |
| M3 | 8/16 | +1 | 0 | pm-01, pm-03, sv-01 | 32 | 0 |
| M4 | 9/16 | +2 | 0 | pm-03, sv-01 | 32 | 10 |
| M34 | 10/16 | +3 | 0 | pm-01, pm-03, sv-01 | 32 | 0 (återanvänder M4) |
| **M12+M3+M4** | **13/16** | **+6** | 0 | sv-01 | **26** | 0 |

- Inga regressioner: inget behov som var löst i M0 blir olöst i någon arm. Inga falskt
  RESOLVED i någon arm.
- **M3** löser pm-02 (rollen MONEY→LIABILITY; rätt spann, JEV YES) och gör pm-01
  olöst→**AMBIGUOUS**: rollen blir korrekt NOTICE i stället för DURATION, men det
  ofullständiga delfragmentet konkurrerar fortfarande — behovet blir korrekt återhållet,
  inte falskt löst.
- **M4** löser båda de kontextsvaga partfallen (if-05, if-06) med strukturfönster
  (98 respektive 381 tecken mot 47 respektive 28 i klausulen). De två kvarvarande
  partfallen påverkas inte: pm-07 får 1 av 2 parter verifierade (den andra avvisas
  fortfarande av JEV), och sv-01 får **alla tre parterna korrekt verifierade men
  behovsmodellen (ett värde per behov) blockerar** → AMBIGUOUS. Det svarar direkt på
  kontrollfrågan: kontexten ger rätt avtalspart, inte bara fler namn/roller — inga
  felaktiga värden verifierades.
- **Interaktion:** M3 och M4 är additiva (M34 = M0 + M3 + M4). pm-01 kräver däremot
  **två** förmågor: M2 (släpp delfragmentet) + M3 (rollen) — M3 ensam ger AMBIGUOUS,
  M2 ensam olöst. Det är den enda observerade interaktionen.

### Kvarvarande olösta (3/16)

| Fall | Utfall | Nästa förmåga |
|---|---|---|
| v2-pm-05 | olöst | verifiering/typsemantik (M6) — M1 gav ren presentation, JEV svarar fortfarande NO |
| v2-pm-07 | olöst | verifiering (M6) + flervärdesbehov (M5) |
| v2-sv-01 | ambiguous | flervärdesbehov (M5) |

## Ekonomi — exekvering vs experiment

| Arm | Exekveringskostnad (JEV från tom cache) | Experimentets nya anrop | Inferenser |
|---|---|---|---|
| M0 | 32 | 0 | 0 |
| M3 | 32 | 0 | 0 |
| M4 | 32 | 10 | 0 |
| M34 | 32 | 0 (replay av M4) | 0 |
| M12+M3+M4 | **26** | 0 (replay) | 0 |

Ackumulerat ger **+6 lösta behov** och gör **26 JEV-anrop mot M0:s 32** (6 färre, tack vare
M2:s konsolidering), utan nya modellinferenser. M4:s 10 nya anrop är experimentets
engångskostnad för de kontextnycklade svaren — strategins exekveringskostnad är 32/26.

## D10-svarskontamination

Clause-level proxy (löst behov som använder värde utanför gold): **0 i alla armar**.
Äkta D10 kräver svarsnivåfacit (v2 är klausulnivå) och körs på det nya oberoende
testsetet; v1-referens 0/20.

## Slutsatser

1. **Rollrobusthet (M3) är billigt och säkert:** +1 löst, 0 nya anrop, och det enda
   utfallsbytet i fel riktning är att pm-01 blir korrekt AMBIGUOUS i stället för olöst.
   Det bekräftar att rollförståelse var en verklig flaskhals.
2. **Kontextfönster (M4) är rätt för partsidentifiering:** strukturstyrda, behovsanpassade
   fönster löser båda kontextsvaga fallen och ger rätt parter även där behovsmodellen
   blockerar. Det friköper inte flervärdesbehovet.
3. **Ackumulerat 13/16 (+6), 0 falskt RESOLVED, 26 mot 32 JEV-anrop.** Kvarvarande tre
   behov pekar på M5 (flervärde) och M6 (verifiering) — inte på GLiNER2.
4. **Nästa steg enligt beslutet:** inga fler armar förrän M5/M6 beslutas. M5 ska vara ett
   eget, tydligt avgränsat experiment eftersom det ändrar definitionen av när ett behov är
   RESOLVED.

## Reservation

De 16 fallen är nu en diagnostisk utvecklingsmängd för M1–M6, inte ett oberoende blindtest
för de förbättrade versionerna. Ett nytt osynligt dokumenttest krävs innan bredare
aktivering. #450 (revisionen) och #451 (M1/M2) är oförändrade.
