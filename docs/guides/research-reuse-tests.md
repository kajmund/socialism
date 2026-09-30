# Research reuse: fyra isolerade steg

Testgruppen `backend/tests/research_reuse/` gör återanvändningens fyra krav
synliga var för sig. Produktionsflödet läser och bedömer huvudfrågan före
uppdelning. Samma kontroll körs för varje underfråga innan extern sökning.
Bedömningen ser huvudfrågans kontext. När hela huvudsvaret räcker sparas den
bedömningen och dess källunderlag direkt; ingen andra bedömningsrunda eller
uppdelning behövs. Fingeravtrycket för fullständighet inkluderar även kontexten.
Frysta svar med hela källunderlaget och faktisk bedömning publiceras som
`research.answer` med `research.answered_by` i Graph v2. Ingen återanvändning
läser legacy claims eller Question→Evidence-länkar.

| Steg | Testfil | Kontrakt |
| --- | --- | --- |
| 1 | `test_01_main_lookup.py` | Läs Graph v2 för huvudfrågan före uppdelning; bevara källa, version och kundgräns. |
| 2 | `test_02_reuse_decision.py` | Bedöm svaret mot frågan; tillräckligt underlag ska stoppa extern källsökning. |
| 3 | `test_03_remaining_gaps.py` | Planera bara luckor; köa inte samma kanoniska fråga igen. |
| 4 | `test_04_main_answer.py` | Bevara komplett respektive partiellt svar och gör huvudsvaret återanvändbart i Graph v2. |

## CI och snabb lokal verifiering

Från `backend/`:

```sh
uv run pytest tests/research_reuse -m research_reuse -rxX --durations=0
uv run pytest tests/research_reuse/test_02_reuse_decision.py -rxX
```

CI kör gruppen i det egna obligatoriska jobbet **Research reuse contracts
(steps 1–4)**. De fyra vanliga backend-shardarna exkluderar gruppen.
Databasen är en temporär SQLite-fil; modell-, embedding- och källgränser mockas.
Gruppens autouse-fixture blockerar socketanslutningar: en glömd mock är ett fel.
En pool med en enda koppling används för att upptäcka att anrop behåller databasen
medan externa tjänster körs. Inga riktiga nycklar eller databaser behövs i CI.
JUnit-resultat med tider sparas som artefakten `research-reuse-contracts` och
jobbsammanfattningen visar passerade, ofärdiga och felande kontrakt separat.

Alla fyra kontrakt ska passera; inga XFAIL eller förväntade produktfel finns.
Testerna omfattar också två på varandra följande körningar, en omformulerad
huvudfråga, kvarvarande luckor, partiella svar, källornas ålder,
kund/case/modulgränser samt tillgänglig databaskoppling vid modellfel och avbrott.
De flesta tester kör ett enda steg. Smala integrationstester verifierar att
stegen är inkopplade i produktionsflödet utan REST eller bakgrundsworker.

## Iteration med riktiga tjänster

Kör verktyget från din konfigurerade `backend/` med dess `.env`:

```sh
uv run python scripts/check_research_reuse.py --live --attempt-id ATTEMPT --step 1
uv run python scripts/check_research_reuse.py --live --attempt-id ATTEMPT --step 2 --repeat 5
uv run python scripts/check_research_reuse.py --live --attempt-id ATTEMPT --step 3
uv run python scripts/check_research_reuse.py --live --attempt-id ATTEMPT --step 4
```

`ATTEMPT` är en befintlig research med sparad huvudfråga. Verktyget är fristående
från pytest, så CI:s testnycklar, SQLite-fixtures och mockar laddas inte.
`--live` är obligatoriskt. Saknad konfiguration och tjänstfel ger fel och
exitkod skild från noll; inga ersättningstjänster används.

- **Steg 1:** riktig OpenAI-embedding och Graph v2-hämtning från konfigurerad
  databas. Det mäter embedding och grafhämtning separat och sparar grundat underlag.
- **Steg 2:** den konfigurerade research-assessorn, med aktuella databaslagrade
  prompts, bedömer underlaget från steg 1. Ingen ny embedding eller källhämtning.
- **Steg 3:** produktionsadaptern för följdfrågor och dess vanliga validering
  körs mot bedömningen från steg 2. Vid `sufficient` anropas ingen planner.
  Samma `plan_question_gaps` används av huvudfrågans produktionsflöde.
  Den isolerade körningen planerar luckor; kanonisk ködeduplicering och nästa
  frågas återanvändningskontroll verifieras separat i CI-gruppen.
- **Steg 4:** befintliga researchens underlag skickas genom produktionsfunktionens
  svarsfångst. Riktiga databasändringar inspekteras och rullas sedan tillbaka.
  Huvudfrågans svar och dess `research.answered_by`-projektion måste finnas
  för att kontraktet ska passera. Äldre körningar utan en uttrycklig bedömning
  av huvudfrågan publiceras som partiella. Bara frysta EvidenceSet får bli
  återanvändbara svarsepisoder.

För ett enskilt befintligt ResearchNeed lägg till `--need-id NEED` i steg 1–3.
Steg 4 granskar alltid huvudfrågan. För att även köra den riktiga lagen.nu-adaptern
för en av de planerade luckorna:

```sh
uv run python scripts/check_research_reuse.py --live --attempt-id ATTEMPT \
  --need-id NEED --step 3 --fetch-gap 1
```

Den valda luckan måste begära exakt en av lagen.nu:s källtyper. Detta kör riktig
MCP-hämtning, passageval och tolkning med konfigurerade tjänster och prompts.
Det startar ingen Attempt, ingen bakgrundsworker och ingen provider-ingestion
eller vektorupsert. Källevidens med status `error` ger exitkod 1 och sparas
i resultatfilen; den ersätts inte med andra källor.

`--step all` kör de fyra proberna i ordning; `--repeat N` mäter upprepningar.
`--workspace DIRECTORY` väljer resultatmapp. Standardmappen är
`backend/data/research_reuse_lab/ATTEMPT/NEED/` (eller `main/`).

## Replay och tidsmätning

`step_1.json` sparar evidens, `step_2.json` bedömningen, `step_3.json` luckor och
eventuell källevidens, `step_4.json` projektionens kontrollresultat.
Replay är ett uttryckligt val av sparat testunderlag, inte en produktionsfallback.
Filer binds till Attempt, fråga och kund/case/modul. En bedömning binds dessutom
till exakt underlag från steg 1. Fel kontext, saknad fil eller en ändrad föregångare
avvisas; verktyget kör inte tidigare steg automatiskt.

`timings.json` innehåller varje repetitions tid, delmoment, utfall samt median
och p95 per steg. Modell, embeddingmodell och hash av aktuella prompts sparas
utan nycklar eller databaskopplingssträng. Initiering ingår inte i stegtiden.
Prompts kan ändras mellan omkörningar av steg 2 utan att källorna hämtas igen.
Vid ändringar i graf, källor eller färskhetspolicy måste steg 1 köras om:
verktyget bedömer uttryckligen den sparade ögonblicksbilden, inte en aktuell graf.
CI-tider gäller mockade tester och ska inte tolkas som tjänsternas prestanda.

Proberna använder egna korta databastransaktioner. Embedding och modellarbete
körs med kopplingen återlämnad till poolen. Steg 4 har inga externa anrop inom
sin skrivtransaktion och committar inte granskningsändringarna.

### Gap-planning performance

Follow-up legal validation runs in bounded parallel tasks using
`research_need_concurrency`. Results preserve draft order; failed or cancelled
batches cancel and await all sibling tasks. Identical draft questions merge
source requirements before validation. Different legal tracks require separate questions.

Live step 3 records `follow_up_model`, `legal_validation` and individual
`legal_validation_N` durations. Each measurement includes `llm_calls` with
actual provider, model, reasoning effort, selected configuration, token counts,
retries and failures. The top-level configuration describes the default only.

The follow-up catalog prompt requests focused non-overlapping
questions covering assessed gaps, keeping independent information needs separate. Existing database prompt text is insert-only:
update that field explicitly through the prompt editor when adopting this change.
Do not overwrite customer overrides automatically.
