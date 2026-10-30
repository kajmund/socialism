# GLiNER2 som valbar förmåga i SWE Investigation — integrationsspec

**Status:** beslutsunderlag och förberedelse. Beslutet är fattat: godkänn GLiNER2
som **valbar** förmåga i SWE:s Investigation-lager, **avstängd som standard** och
utan påverkan på dagens Research. Denna spec definierar vad som integreras, hur
det återanvänds, och vilka acceptanskriterier som gäller före implementation.

## 1. Beslutsgrund (mätresultaten, alla frysta i main via PR #443–#446)

| Bevis | Resultat |
|---|---|
| PR #443 blindtest v1 (3 nya verkliga avtal) | baslinje 0/20 → frusen kombination 14/20; unik täckning 9/13 |
| PR #444 D10 | 0 kontaminerade svar på samtliga 20 fall |
| PR #445 E1 datum (`span-date-v1`, endast DATE-behov) | datumfall 2/4 → 4/4, inga regressioner |
| PR #445 E2 spannekvivalens | "en dagfrist" ≡ "en dagfrist"; bt-03 false-RESOLVED → korrekt |
| PR #446 E3 operativ roll-kontroll | bt-17 dold risk → korrekt svar; **19/20 korrekta utfall, 0 kontamination, 0 dold evidensrisk** |

**Reservation (bokförd, inte bortglömd):** D10 v3 är en återspelning av den
förbättrade kedjan mot samma dokument — inte ett orört blindtest. Ett nytt
oberoende test på osedda dokument verifierar den färdiga versionens
generalisering. Detta **blockerar inte** en isolerad, avstängd integration men
måste vara gjort innan någon bredare aktivering.

**Uppdatering 2026-10-30 — blindtest v2 utfört:** den färdiga kedjan mättes på tre
nya, osedda avtal (leverantörsvillkor, servitut, försäkringsspecifikation):
baslinje 2/16 → frusen kombination 7/16, 0 falskt RESOLVED, 2 korrekt AMBIGUOUS,
13 inferenser + 24 JEV-anrop för 5 extra lösta behov. Resultatet ger underlag för
fortsatt integration som valbar, avstängd förmåga men **inte** för bredare
aktivering: parter (0/4) och ansvarsbegränsning (0/1) är svaga, och två
artefaktklasser (radbrytningar i spann, minimala klausuler) plus E3-rollklassning
av ansvarstak behöver ett separat nästa experiment. Detaljer och frysta
slutsatser: `docs/architecture/gliner2-generalization-protocol.md`.

## 2. Vad som integreras (den frusna kombinationen, oförändrad)

- **GLiNER2** `fastino/gliner2.5-multi-v1`, threshold 0.3, CPU — som
  **behovsstyrd, valbar spann-förslagsgivare**, anropad **endast vid kvarstående
  REQUIRED-gap** efter den billiga deterministiska undersökningen (S2-strategin).
- **JEV arm D** `span-need-contrast-v1` som det enda behovsspecifika kontrastiva
  beslutet; `span-date-v1` endast för DATE-behov.
- **Evidenskontraktet:** typkontroll (ordformsdatum inkluderat), kanonisk
  spann-normalisering, VERIFIED/AMBIGUOUS/REJECTED, **operativ roll-kontroll
  (E3)** — AMBIGUOUS härleds från konkurrerande kandidater i samma operativa
  roll; obestämd roll → konflikten kvarstår synlig.
- **Rollfördelningen (oförändrad):** GLiNER2 föreslår aldrig entitetstyper som
  godkänns automatiskt; JEV avgör betydelsen; SWE:s kontrakt avgör användning.
  En NER-confidence får aldrig ensam kringgå ett operationskontrakt eller
  markera ett behov som RESOLVED. En lärd policy får bara välja *vilket*
  tillåtet steg som körs — aldrig åsidosätta kontrakt.

## 3. Reuse-vs-new-matris

| Komponent | Befintlig motsvarighet | Beslut |
|---|---|---|
| JEV-anrop | `backend/app/jev/system.py` (JevSystemOne) | **Återanvänd** |
| Behovsmodell / gap-analys | research-tjänsternas behovsstatus (REQUIRED/SUPPORTING/EXPLORATORY-logiken i research-arbetsflödet) | **Återanvänd**; mappas exakt i implementations-PR |
| Deterministisk extraktor | befintlig kandidatgenerator i research-pipelinen | **Återanvänd** |
| Evidenskontrakt (typkontroll, normalisering, VERIFIED/AMBIGUOUS/REJECTED, rollkontroll) | nytt — men som typade regler i data, inte ett nytt ramverk | **Ny, liten** (port av de frusna reglerna från experimenten; enhetstestade) |
| GLiNER2-inferens | ingen i produktionen | **Ny, isolerad adapter** (egen modul, subprocess/venv, CPU-först) |
| Switch | `backend/app/config.py` | **Ny inställning**, `false` som standard |
| JevSpan, E/F/G-tresteg, D2-prompt, tränade policies, fine-tuning | — | **Integreras inte** — förkastade med mätdata |

## 4. Integrationens form (oförhandlingsbart)

1. **Avstängd som standard:** `gliner_span_proposer_enabled=false`. Avstängt
   läge är bit-identiskt med dagens Research: ingen modul laddas, inga extra
   anrop, ingen extra latens.
2. **Opt-in per körning:** påslag sker per research-körning, aldrig globalt
   utan explicit konfiguration. Ingen aktivering för alla användare eller alla
   dokument i detta steg.
3. **Inga fallbacks:** påslagen och GLiNER2 felar → körningen felar högljutt.
   Ingen tyst återgång till "bara extraktorn". (Konsekvent med "no fallbacks".)
4. **Importriktning:** `backend/app` importerar aldrig `crates/swe-gym`
   (experimentcratens non-negotiable #6). Adaptern placeras under
   `backend/app/services/research/` och pratar med modellen via en isolerad
   process; experimentartefakterna förblir referens.
5. **Budget:** GLiNER2-inferens och JEV-anrop redovisas i existerande
   kostnadsredovisning (per-körningsbudget), aldrig utanför tak.
6. **Databasdisciplin:** ingen databasanslutning hålls öppen över
   GLiNER2-/JEV-anrop (rot-AGENTS.md:s hårdaste regel).

## 5. Acceptanskriterier (före "klar")

1. Avstängt läge: existerande research-tester oförändrade, 0 extra anrop
   (integrationstest som bevisar det).
2. Påslaget läge, integrationstest på riktiga fall: (a) ett fall där GLiNER2
   behövs (g4-05-klass: omskriven klausul utan nyckelord) löses via förslag →
   arm D → kontrakt; (b) ett fall där extraktorn räcker — GLiNER2 anropas
   aldrig (ingen kostnad); (c) ett negativt fall utan gap — inget anrop.
3. Kontraktsreglerna (typkontroll, ordformsdatum, kanonisk normalisering,
   rollkontroll med fail-safe för obestämd roll) som enhetstester.
4. Switch-test: disabled-konfigurationen producerar identiskt resultat och
   identisk kostnadsbild som dagens Research.
5. Högljudd felhantering: GLiNER2-processfel ger ett tydligt fel, inte en tyst
   reducering.

## 6. Öppna punkter inför implementation

- **Model hosting:** lokalt körs modellen i en isolerad venv (dagens
  experimentmönster); projektet har ingen vald hosting-target, så
  produktionshosting dokumenteras som öppen fråga — inte ett blockande krav.
- **Behovsmodellens exakta plats** i produktionen mappas i implementations-PR:en
  (kandidatgenerator → gap-analys → verifiering) och visas med testet i
  kriterium 2.
- **Nästa oberoende blindtest** på osedda dokument (nya avtal) planeras separat
  och måste passera innan någon bredare aktivering.

## 7. Svaret på den ursprungliga frågan

GLiNER2 är värd att behålla — som behovsstyrd, valbar spann-förslagsgivare med
uppmätt marginalnytta (0→14/20 på nya avtal). JevSpan behöver inte integreras
(överlapp och bristande evidens dokumenterat). SWE kan utnyttja kombinationen
med befintlig JEV och befintliga evidenskontrakt — utan ytterligare en parallell
AI-arkitektur.
