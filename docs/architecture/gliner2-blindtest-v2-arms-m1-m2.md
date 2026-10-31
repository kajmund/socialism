# Blindtest v2 — ablationsarmar M1 (whitespace) och M2 (spann-gränser)

**Status:** diagnostisk utvecklingskörning på det frysta blindtest v2-materialet.
M0 är oförändrad fryst referens; #450 (behovsrevisionen) är orörd. Inga modeller har
körts och inga avtalsdata har committats (repot är publikt: artefakterna innehåller
endast case-id, typer, utfall, hashar, offset och antal).

## Design

| Arm | Innehåll |
|---|---|
| **M0** | fryst kedja (blindtest v2), exakt referens |
| **M1** | presentationsnormalisering av extraktionsartefakter (radbrytningar, delade datum) |
| **M2** | spann-gräns-konsolidering: kandidatfragment som är strikt innehållna i ett längre spann i samma fall släpps |
| **M12** | M1 + M2 |

- **Inga GLiNER2-inferenser** i någon arm: kandidatlistorna är frysta. M0 återanvänder
  de frysta JEV-svaren; M1 gör nya JEV-anrop **endast** för presentationer som faktiskt
  ändras (2 anrop, frysta i `jev_span_fixtures_v2_arms.json`). M2 återanvänder allt.
- Körning: `backend/.venv/bin/python crates/swe-gym/tools/blindtest_v2_arms.py`
  (fullständigt material utanför repot; artefakter i `crates/swe-gym/benchmarks/`).

### M1 — invariant för källa och proveniens

Normaliseringen rör **endast presentationen för matchning/verifiering**:

1. whitespace-sekvenser kollapsas till ett mellanslag,
2. en space efter bindestreck inuti ett datum repareras (`2024-09- 21` → `2024-09-21`)
   — regeln kräver siffra före bindestrecket, så intervallseparatorer (` - `) bevaras.

Den kanoniska källtexten ändras aldrig. För varje normaliserat spann sparas
`original_span_sha256`, `normalized_span_sha256`, `changed` samt spannets
start/slut-offset i den extraherade klausulen, så en träff kan pekas tillbaka till
exakt position i originaltexten. Instrumentet assertar dessutom att
`despace(normaliserad) == despace(original)` — ingen innehållsändring.

### M2 — gränsregel

En kandidat släpps **endast** om dess kanoniska form är en strikt delsträng av ett
längre spann (gold eller annan kandidat) **i samma fall**. Inga sammanslagningar av
närliggande spann, ingen proximity-heuristik. Varje släppt kandidat loggas med
innehållande spann-typ (gold/candidate) och hash.

## Resultat

| Arm | Lösta | Förändring | Falskt RESOLVED | AMBIGUOUS | JEV-anrop (nya) | Inferenser |
|---|---|---|---|---|---|---|
| M0 | **7/16** | — | 0 | pm-03, sv-01 | 32 (0) | 0 |
| M1 | **8/16** | +1 | 0 | pm-03, sv-01 | 32 (2) | 0 |
| M2 | **8/16** | +1 | 0 | sv-01 | 26 (0) | 0 |
| M12 | **9/16** | +2 | 0 | sv-01 | 26 (0) | 0 |

### Per fall (endast ändrade fall)

| Fall | M0 | M1 | M2 | M12 | Orsak |
|---|---|---|---|---|---|
| v2-sv-03 | olöst | **löst** | olöst | **löst** | M1: datumartefakten repareras → JEV YES |
| v2-pm-03 | ambiguous | ambiguous | **löst** | **löst** | M2: två delfragment släpps → endast hela värdet kvar |

Övriga 14 fall är oförändrade i alla armar. Inga försämringar och inga nya
falskt-RESOLVED i någon arm.

### M1 falsifierade revisionens hypotes för pm-05

Behovsrevisionen attribuerade pm-05 till material/whitespace. M1 ger JEV den rena
presentationen (`tretton (13) månader`) och JEV svarar fortfarande **NO**. Felet ligger
alltså inte i extraktionsartefakten utan i **verifieringen/typsemantiken** (spannet är en
frist/deadline, och PERIOD-kontrasten skiljer tidsperiod från tidsfrist). M1 återställer
därför bara 1 av de 2 förväntade fallen. Det är exakt vad ablationen ska avslöja:
revisionens motfaktiska hypoteser var hypoteser, inte mätningar.

### M2:s interaktion med M3 (rollrobusthet)

M2 släpper även delfragmentet i pm-01 (innehållet i det längre värdet), men behovet
förblir olöst eftersom operativ roll klassas som DURATION medan behovet deklarerar NOTICE
— rollrobusthet (M3) krävs. Samma sak gäller pm-02. Ablationen visar alltså att M2 är
nödvändig men inte tillräcklig för de fallen.

## Ekonomi

- **Inferenser:** 0 i alla armar (post-processing).
- **JEV:** M0 32 anrop; M1 32 (varav 2 nya); M2 26 (0 nya — konsolideringen tar bort 6
  verifieringar); M12 26 (0 nya efter M1:s cachade svar).
- **Merkostnad per ytterligare löst behov:** M1 = 2 nya JEV-anrop för +1; M2 = 0 nya
  anrop för +1 (och 6 färre verifieringar); M12 = 2 nya anrop totalt för +2, med
  6 färre JEV-anrop än M0 som helhet.

## D10-svarskontamination

Blindtest v2 har **klausulnivåfacit**, inte svarsnivåfacit. Här rapporteras därför
**proxy**: ett löst behov som använder ett verifierat värde utanför gold. Resultat:
**0 kontaminerade svar i alla armar**. Den sanna D10-mätningen (svarsnivå, inklusive
korrekta avståenden) kräver ett svarsnivåfacit och ska köras på det nya oberoende
testsetet innan bredare aktivering. v1-referensen är 0/20 kontaminerade svar.

## Slutsatser

1. **Båda åtgärderna är billiga, deterministiska och GLiNER2-oberoende** — och de
   levererar: +2 lösta behov (9/16) utan nya inferenser och utan nya falskt-RESOLVED.
2. **M2 är strikt bättre än M1 på ekonomi** (0 nya anrop, 6 färre verifieringar) och
   löser ett fall som M1 inte rör.
3. **Varken M1 eller M2 räcker för rollklassning, kontextfönster eller flervärdesbehov.**
   De kvarvarande olösta är nu: pm-01/pm-02 (roll, M3), pm-05 (verifiering, M6),
   pm-07/sv-01 (flervärde, M5), if-05/if-06 (kontext, M4).
4. **Nästa armar:** M3 (rollrobusthet), M4 (behovsanpassat kontextfönster), M5
   (flervärdesbehov — eget, tydligt avgränsat experiment), M6 (verifieringsåterhämtning).
   Samma protokoll: M0 fryst, separat arm per förmåga, kombinationsarm, per-fall-utfall,
   båda måtten och kostnad per åtgärd.

## Reservation

De 16 fallen är nu en **diagnostisk utvecklingsmängd** för M1–M6, inte ett oberoende
blindtest för de förbättrade versionerna. Ett nytt, osynligt dokumenttest krävs innan
bredare aktivering. Behovsrevisionen (#450) och blindtest v2-resultaten lämnas orörda.
