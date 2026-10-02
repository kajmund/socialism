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

`test_01_sufficient_knowledge.py` verifierar dessutom det första kontraktet genom
hela produktionsflödet: tillräckligt grundad Graph-kunskap avslutar huvudfrågan,
och nästa körning återanvänder dess sparade svar. Källhämtning, dokumentinläsning,
chunkning, vektorindexering och följdfrågeplanering får inte anropas. Dokument-
och TextUnit-antal samt versionshänvisningar bevaras. Frågans embedding tillåts
för retrieval; inga källtexter får skickas för embedding. TTL-underlaget fångas
utan Jev-anrop och samma svarsversion behåller sin granskningspost. Bedömningen
mockas: testet verifierar flödeskontraktet, inte juridisk svarskvalitet eller att
temporal historiksökning och hashåteranvändning redan är fullständigt implementerade.

`test_02_cached_source.py` verifierar nästa övergång för både huvudfrågan och
underfrågor: befintlig Graph-kunskap bedöms som otillräcklig, varefter lagen.nu-
adaptern använder cachade TextUnits och deras sparade embeddings. Ny evidens
bedöms därefter som tillräcklig. Dokumentversion, text, chunkarnas SHA-nycklar
och källhänvisningar bevaras. Dokumenthämtning, ingestion, chunkning och
ersättning av dokumentets vektorer får inte anropas. Saknade sparade vektorer
ger ett uttryckligt källfel utan återhämtning eller om-embedding.

Källsökning för att identifiera dokumentet, embedding av frågan, Jevs passageval
och tolkning av texten kan fortfarande behövas: cachad text betyder inte att
frågan redan är besvarad. CI mockar dessa externa gränser och själva bedömningen,
men använder produktionsfunktionerna och en riktig testdatabas. Kontraktet gäller
återanvändning inom samma dokumentversion; delade chunks mellan olika dokument
och temporal invalidering verifieras i separata kontrakt nedan.

`test_01_saved_answer.py` verifierar fyra kombinationer genom produktionsflödet:
ett tidigare huvud- respektive undersvar återanvänds som huvud- respektive
underfråga. Kanonisk frågeidentitet och båda originalkällorna måste bevaras.
Assessorgränsen kontrollerar att underlaget kommer från sparade svarsepisoder
och att den enda databaskopplingen är ledig. Samma förbjudna käll-, chunk-,
index- och TTL-gränser används som i huvudfrågetestet. Ingen ny fråga får skapas.

## Bedömningens källunderlag

`test_assessment_input.py` kontrollerar bedömningens kompakta inmatning.
Assessorn får hela de redan utvalda källutdragen, utan den tidigare kapningen
vid 2 000 tecken. Identiska stycken skickas en gång i `passages`; varje
evidensrad har ordnade `passage_ids`. Sammanfogning ger exakt originalutdraget,
inklusive Unicode och blanksteg. Detta ändrar bara modellens inmatning:
dokument, chunks, SHA, embeddings och sparade källreferenser ändras inte.
Tidigare begränsningar vid hämtning/tolkning kan fortfarande finnas och deras
markeringar bevaras. Fullständighetsbedömningens separata adapter ändras inte.

Källor med samma text behåller olika källidentiteter. Korta `evidence_id` och
`source_id` gäller endast det aktuella modellanropet. Stödreferenser översätts
till original-ID innan den vanliga kontrollen av frågetillhörighet körs.
Passage-ID och okända stödreferenser kan inte bli källhänvisningar. Strukturerad
juridisk analys, verifierade citat, claims, kvalitetsvarningar och tidsmarkeringar
bevaras. Opaque lagringsreferenser, anropsdiagnostik och tidigare svarsbetyg
ingår inte i modellunderlaget. `graph_fact_text` är en utsaga att kontrollera
mot källpassagerna, inte självständigt belägg.

Formatinstruktionerna ligger i `research_assessment_prompt.py` och ingår via
`prompt_catalog.py` i modulernas vanliga databas-seed. Testerna seedar en tom
databas för dd, politik och expertgranskning. Runtime läser fortsatt prompten
från databasen. Befintliga prompttexter och kundöverskrivningar uppdateras inte
av seed: uppdatera `research.assessment.system` uttryckligen vid införandet.
Modellvalet ändras inte av denna optimering.

`test_assessment_quotes.py` omfattar också överlappande citat, olika källor och
roller, Unicode/blanksteg, citat utanför valt utdrag samt 79 unika analyser med
upprepade källcitat. Analysens återkommande text delar samma `passages` som
källutdragen. Matchningen är exakt; korta unika texter lämnas direkt i fältet.
Styckeseparatorer bevaras som egna passager så att ett stycke kan återanvändas
även när ett annat utdrag slutar före separatorn.

Upprepade fältnamn i `legal_result` skickas en gång i `legal_schemas`.
Varje analysobjekt har `schema_id` och `values`, med samma fältordning som
schemat; detta gäller även nästlade objekt. Alla originalvärden behålls,
inklusive null, tomma listor, negativa utfall, källadresser och span-ID.
Testerna rekonstruerar hela originalanalysen, inte bara citaten. Textdelning
gör inte analys till primärkälla. Prompten förklarar både formatet och skillnaden.
JSON serialiseras utan formateringsblanksteg; blanksteg inne i text ändras inte.

Modellfel för kontextgräns, för långt svar och timeout har olika felmeddelanden.
`research.assessment.failed` loggar säker felkategori, undantagstyp, antal
evidensposter/granskningsgrupper och inmatningens teckenantal, utan källtext
eller leverantörens felkropp. Orsaksundantaget bevaras och inga alternativa
modeller eller källvägar används.

### Isolerad Qwen-mätning 2026-10-02

Samma sparade underlag från research `b0187407f2d54abfb7b83ee2f7d190ff`
(21 evidensposter, 16 granskningsgrupper) bedömdes med konfiguration 3,
Qwen 3.8 27B och medium reasoning. De nya katalogprompterna seedades i en
isolerad SQLite-databas för förhandskontrollen; produktionsprompterna ändrades
inte. Huvud-/underfrågan med stöd, en fråga om HD-avgöranden 2026 utan stöd
och ett underlag med bara en källtitel kördes två gånger vardera. Dessa åtta
kontroller kompletterades med två kontroller av beslut med oförenliga datum.
Alla tio förväntade utfall passerade med originalreferenser efter översättningen.
Inga källor hämtades och inga research- eller grafposter skrevs.

| Mått för de fyra positiva kontrollerna | Före | Efter |
| --- | --- | --- |
| Median inmatningstokens | 38 627 | 32 149,5 |
| Median bedömningstid | 5,29 s | 5,16 s |
| Tillgänglig utvald källtext | 31 145 tecken efter kapning | 101 525 tecken, delad som 59 131 unika tecken |

Originalutdrag rekonstruerades exakt i alla 16 grupper. Färre tokens trots
mer källtext är den säkra observationen; en stabil tidsvinst har inte visats.
Jämförelsen avser samma frysta evidens men olika serialisering och
formatinstruktioner. Den är inte en mätning av hela researchkedjan eller ett
bevis för generell bedömningskvalitet. En tidigare iteration stoppade ett
tillräckligt svar eftersom modellen klassade en förenlig skillnad i betoning
som motsägelse. Prompten skiljer nu sakmotsägelser från nyanser i rationale;
återanvändningskontrollen blockerar fortfarande rapporterade sakmotsägelser.

### Kontextöverskridandet i expertchatten 2026-10-02

Huvudfrågan ”Hur tillämpas 36 § avtalslagen i svensk rättspraxis?” gav
79 Graph v2-poster och 77 granskningsgrupper. Cerebras avvisade den tidigare
inmatningen med `context_length_exceeded`: begärd längd 169 124, gräns 131 072.
De tidigare kontrollerna ovan använde den smalare frågan med 21 poster och
upptäckte därför inte denna storleksregression.

Med samma 79 sparade poster, samma Qwen-konfiguration och den nya seedade
formatprompten krävdes 122 384 inmatningstokens. I två slutkontroller blev
utfallet `sufficient` efter 8,80 respektive 6,32 sekunder, med 6 224 respektive
5 290 utmatningstokens och inget extra modellförsök. Alla 77 källutdrag och
hela deras strukturerade analyser rekonstruerades exakt. Varken hämtning,
embedding eller grafskrivning ingick i kontrollerna. Tio separata kontroller
av tillräckligt/otillräckligt underlag och oförenliga datum passerade också.

En tidigare kontroll av det slutliga formatet lyckades på 15,43 sekunder,
medan nästa fick en timeout efter 60 sekunder. Den misslyckade kontrollen
räknas inte som passerad. Förlustfri delning löser detta reproducerade
kontextöverskridande, men garanterar varken godtyckligt stora underlag eller
tjänstens svarstid. Dessa fel förblir synliga. Produktionsinförandet kräver
att den aktiva databaslagrade formatprompten uppdateras tillsammans med koden;
förhandskontrollerna uppdaterade inte produktionsprompten.

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
Adaptern får sin databas, embeddingtjänst och vektorlagring, precis som vid vanlig
källhämtning. Den återanvänder tillgängliga TextUnits och embeddings; vid en
cachemiss kan den hämta texten, dela upp den, skapa embeddings och spara dokumentet samt skriva
providerunderlag. Dessa ändringar committas. Den startar ingen Attempt eller
bakgrundsworker. Resultatets `reused_text_units`, dokumentversion och TextUnit-ID:n
visar när cachen användes; jämför kalla och varma körningar separat.
Källevidens med status `error` ger exitkod 1 och sparas
i resultatfilen; den ersätts inte med andra källor.

`--step all` kör de fyra proberna i ordning; `--repeat N` mäter upprepningar.
`--workspace DIRECTORY` väljer resultatmapp. Standardmappen är
`backend/data/research_reuse_lab/ATTEMPT/NEED/` (eller `main/`).

## Replay och tidsmätning

### Strikt prov av ett tillräckligt sparat svar

För att verifiera just återanvändningen utan att köra en hel research:

```sh
python scripts/check_sufficient_answer_reuse.py --live --attempt-id ATTEMPT \
  --need-id NEED --repeat 2 --output new-child-report.json
python scripts/check_sufficient_answer_reuse.py --live --attempt-id ATTEMPT \
  --need-id NEED --as-main --repeat 2 --output new-main-report.json
```

Utelämna `--need-id` för den ursprungliga huvudfrågan. `--as-main` prövar en
sparad underfråga som ny huvudfråga med samma kanoniska identitet och
huvudfrågans vanliga indata; det skapar ingen ny Attempt. Kontextens
kund/case/modul bevaras. Ett undersvar kan räcka för just den frågan även när
den tidigare researchens bredare huvudfråga fortfarande saknar ett komplett svar.

Provet läser aktuell Graph v2 med den beständiga embeddingcachen och bedömer
underlaget med den aktuella databasstyrda assessorn. Frågans embedding får
återanvändas eller beräknas; ingen källtext embeddas. Minst en färsk sparad
`research.answer` måste bidra med evidens. Därefter måste en ny bedömning passera
produktionsflödets kontroll av sufficiens och giltiga stödreferenser.
Vid tillräckligt stöd kontrolleras även att den vanliga luckfunktionen ger noll
följdfrågor utan att skapa en planner. Ett tidigare `sufficient`-fält räcker
alltså inte för att godkänna provet.

Saknat sparat svar eller otillräckligt stöd ger exitkod 1. Provet stannar då;
det hämtar inga nya källor och försöker inte fylla luckan. Modell- och databasfel
fortplantas. Källhämtning, ingestion, chunkning och indexering ingår inte i
provet; att hela orkestreringen avstår från dessa anrop verifieras av CI-testerna
ovan. Provet publicerar inte svarsepisoder eller ändrar den tidigare researchen.
Det kan skriva cacheposter för frågans embedding. Äldre research måste först
ha publicerats via den ordinarie svarsfångsten från sitt frysta underlag;
saknade episoder skapas inte automatiskt här.

Rapporten sparar varje repetitions underlag, svarsfakt-ID:n, ny bedömning,
modellstatistik och separata tider för embedding, grafhämtning och bedömning.
En befintlig rapport skrivs inte över. CI testar även att provet avvisar
otillräckliga bedömningar, påhittade stödreferenser och saknade sparade svar,
med riktiga SQL-transaktioner och mockade modellgränser.

Ett verkligt prov 2026-10-01 använde `need_2` från den frysta researchen
`b0187407f2d54abfb7b83ee2f7d190ff`: frågan om förarbetenas uttalanden om
36 § avtalslagens syfte och funktion. Dess underlag publicerades först genom
ordinarie svarsfångst; två av researchens 15 svar var tillräckliga och resterande
13 förblev partiella. Den bredare ursprungliga huvudfrågan förblev otillräcklig.
Inga tidigare bedömningar eller researchstatusar ändrades.

| Roll | Två prov godkända | Total tid | Bedömningstid |
| --- | --- | --- | --- |
| Underfråga | Ja | 47,25 / 29,25 s | 42,41 / 24,79 s |
| Samma fråga som huvudfråga | Ja | 54,58 / 50,21 s | 47,74 / 43,97 s |

Alla fyra prov hittade samma svarsfakt, fick en ny tillräcklig bedömning och
gav noll följdfrågor. Modellstatistiken visade den konfigurerade assessorn
`deepseek-v4-pro`, reasoning `high`, och cirka 33 000 indatatokens per prov.
21 evidensposter lästes, varav 11 från det sparade svaret. Ingen modellinställning
ändrades. De två rollproven kördes samtidigt, så tiderna är diagnostiska och
utgör inte ett kontrollerat jämförande prestandatest.

### Stegvisa ögonblicksbilder

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

### Verify gap coverage before optimizing question count

Use `scripts/check_research_gap_coverage.py` to repeat only planning and legal
normalization, then evaluate every plan against an explicit human-authored rubric.
The opt-in judge is a separate database-configured prompt, not a production step.
It adds no model call to ordinary research. CI mocks both planning and evaluation;
CI verifies the evaluation contract, not the semantic quality of a live model.

The rubric contains `question`, `assessment_digest` (the digest of step 2's
`payload`, using `snapshots.digest`) and `criteria`, each with `id`, `requirement`
and required `source_types`. Bind the rubric to the saved assessment so it cannot
silently evaluate a different workload. The legal example criteria are in
`backend/tests/research_reuse/fixtures/gap_coverage_36_avtl.json`; add the digest
from your own matching saved assessment before running it.

Seed the catalog fields `research.followup.coverage.system` and `.user` through
the normal prompt catalog setup and explicitly choose the evaluator's model in
admin settings. Missing prompts/configuration/API errors propagate.

```sh
python scripts/check_research_gap_coverage.py --live \
  --attempt-id ATTEMPT_ID --workspace PATH_TO_SAVED_STEPS \
  --rubric BOUND_RUBRIC.json --repeat 5 --output coverage.json
```

Every iteration retains its questions, criterion verdicts, exact question quotes,
source constraints, overlap flags, planning time, separate judge time and actual
model calls. Missing/partial coverage, materially redundant questions or overbroad
questions cause a nonzero exit. Omitting a criterion from the judge response,
invented question IDs, unsupported quotes or missing required source types fail
validation. Existing output files are never overwritten.

The judge is probabilistic, including when the same provider evaluates its own
planner. Review the saved questions and rationales, and use known positive and
negative controls. A passing benchmark on one workload is not proof of universal
coverage or of the accuracy of legal assertions in the assessor's input.

### Isolated legal interpretation and model quality

`check_legal_interpretation.py` replays only `LlmLegalInterpreter` on materialized
source text. It does not fetch sources, route passages with Jev, ingest documents,
start a worker or write research data. Prompt text is read from the real scoped
database; selected model configurations are fixed only in the benchmark process.
It does not change persistent prompt assignments.

```sh
python scripts/check_legal_interpretation.py --live --attempt-id ATTEMPT_ID \
  --inputs legal-inputs.json --configuration-ids 3 2 1 4 \
  --repeat 2 --output new-legal-report.json
```

Inputs are a JSON list of `LegalBenchmarkInput`: `id`, `source` (a
`LegalSourceIdentity`), `question`, `raw_text`, `raw_text_sha256`, `truncated` and
human-authored `expected` criteria. Calculate the SHA-256 of the exact UTF-8
source. Expectations specify `holding_established`, `adjustment_granted`, optional
`court_level`/`decision_basis`, and `forbidden_holding_spans`. Span IDs are `s0`,
`s1`, etc. from splitting that exact text on blank lines, as in the interpreter.
A changed source invalidates the expectations rather than silently reusing them.

Use a short summary with no deciding reasons as a negative control, and include
real deciding reasons, party submissions and dissenting opinions in positive
cases. Mere schema validity and exact quotations do not establish correct legal
attribution: a model can cite a dissent accurately while labelling it majority
reasons. The lab verifies the expected deciding outcome and rejects forbidden
holding spans. Criteria must be reviewed against the supplied source; these
limited checks do not prove the correctness of every legal statement.

Reports preserve interpretations, quality criteria, failed checks, model calls,
reasoning setting, token usage, retries, failures and elapsed time. A schema-valid
but substantively wrong result fails the benchmark. Provider errors are recorded
as failures of that explicitly selected configuration; no substitute model is
used. Cancellation propagates. Existing output files cannot be overwritten.
CI mocks the model boundary and checks majority/dissent attribution, source
binding, failure propagation and database connection release during external work.

Cold and warm source timings must be compared separately. The original source
measurement populated missing TextUnits/vectors; subsequent replays reused them.
A read-only profile found that `SupabaseStorageVectorClient.replace()` scans the
entire index through `_list_keys_for_document()` to find stale document vectors:
87 pages over 8,607 records took 17.53 seconds for one document, of which only 38
records matched. This is a measured separate cost, not an exact attribution of
all uninstrumented time in the earlier run. Four replacements would cost about
70 seconds at that measured rate. No index deletion or replacement was performed
by the inventory profile itself.

That profile describes the former canonical-source replacement path. Canonical
source ingestion now uses version-specific direct writes, keeping historical
vectors and avoiding that inventory scan entirely. The uploaded-file and
document-item replacement paths still use the existing adapter.

Jev passage routing currently uses `settings.jev_timeout_seconds` (3 seconds in
this local setup), rather than `research_jev_timeout_seconds` (5 seconds). An
8000-character/eight-candidate relevance batch can therefore fail even when
research's separate Jev assessment timeout is longer. Timeout settings were not
changed by these benchmarks.

## Kontroll av SHA för chunks

`test_03_chunk_sha.py` verifierar embeddingåteranvändning mellan olika dokument
genom riktig ingestion, SQL och den beständiga embeddingcachen. Varje dokument
använder en ny cacheinstans så att återanvändningen kräver en sparad cachepost.
Identiska chunks återanvänder embedding och behåller separata dokumentversioner
och källhänvisningar. Vid delvis överlapp embeddas endast de nya chunktexterna.
Ändringar i stora bokstäver, mellanslag, skiljetecken eller Unicode-representation
ger egna SHA-nycklar. Embeddingtjänsten får exakt den hashade chunktexten.

Modell, revision och dimension måste också matcha. Den nya cacheversionen
`text.exact.v2` använder inte äldre normaliserade cacheposter som fallback.
Fel och avbrott frigör cacheleasen och databaskopplingen utan att skriva vektorer.
En pool med en enda koppling kontrollerar embedding- och indexeringsgränserna.
CI mockar tjänsterna; testerna verifierar inte embeddingmodellens kvalitet.
Återanvändningen delar embeddingberäkningen. Vektorprojektionerna lagras
fortfarande per dokument; befintliga indexvektorer migreras inte.

`test_04_shared_chunks.py` kontrollerar dessutom gemensam SQL-textlagring med
separata dokument- och versionsrelationer: identiska och delvis överlappande
dokument, versionsföljden A → B → A, samtidiga skrivningar, oföränderliga
chunktexter och innehållsreferenser samt bevarade chunks när en relation tas bort.
Texten ska vara läsbar efter att databassessionen stängts. Samma testgrupp
kontrollerar att externa anrop kan låna den enda databaskopplingen.

`tests/test_shared_chunk_migration.py` verifierar SQLite-migrering och downgrade
med befintliga källhänvisningar samt att felaktiga SHA stoppar migreringen.
PostgreSQL-jobbet i CI kör hela migreringskedjan och därefter
`tests/test_shared_chunk_postgres.py`, inklusive riktig samtidig ingestion.
LLM-, embedding- och indextjänster mockas även där.

PostgreSQL-kontrollerna kan köras isolerat mot en testdatabas:

```sh
TEST_SHARED_CHUNK_POSTGRES_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DATABASE \
  uv run pytest tests/test_shared_chunk_postgres.py -m integration
```

Testerna skapar och tar bort egna tillfälliga scheman; kontot måste få skapa
scheman. De ändrar inte befintliga applikationstabeller och anropar inga externa
modelltjänster. Utan denna variabel hoppas dessa två PostgreSQL-tester över;
SQLite-kontrakten och CI:s obligatoriska PostgreSQL-jobb körs som vanligt.

## Versionsbevarande vektorindexering

`test_05_version_vectors.py` använder riktig canonical ingestion, SQL och
embeddingcache samt den faktiska Supabase-adaptern. SDK:s nätverksgräns mockas
och listning, radering och semantisk sökning förbjuds i testindexet. Kontrakten
kontrollerar kall och varm ingestion, historisk hämtning efter A → B → A,
fel/avbrott, delvis skriven projektion och återindexering av saknade nycklar.
En pool med en enda koppling verifierar både embedding och direkta indexanrop.
Återindexering får inte avsluta en transaktion som tillhör anroparen.

Isolerad mätning med riktig databas, beständig embeddingcache/OpenAI och
Supabase kan köras utan källhämtning, chunkning, LLM-bedömning eller en research:

```sh
python scripts/check_source_vector_index.py --live --document-id DOCUMENT_ID \
  --repeat 2 --output new-index-report.json
```

Detta läser aktuell versions chunk-ID:n och kontrollerar att vektorerna finns.
Saknade vektorer ger en rapport och icke-noll exitstatus. Lägg till `--write`
för att uttryckligen beräkna eller återanvända embeddings via cachen och skriva samma versions kända
projektioner, även om de redan finns. Rapporten skiljer SQL-laddning, direkt
vektorhämtning, cache/embedding plus skrivning och verifiering. En befintlig
rapportfil skrivs inte över. Varken källa, version, frågor eller TTL ändras.

En live-mätning 2026-10-01 av NJA 1989 s. 346, aktuell version med 38 chunks,
gav direkthämtning på 0,77 respektive 0,49 sekunder och cache/embedding plus
direktskrivning på 6,25 respektive 2,46 sekunder. Vektorerna fanns redan före
båda iterationerna; detta är en omskrivningsmätning, inte ett kallt researchflöde.
Ingen helindexlistning eller radering kördes. Tiderna kan inte jämföras som hela
researchtider med den tidigare inventeringskostnaden på 17,53 sekunder.

## Isolerad Jev-screening på fryst underlag

`test_jev_passages.py` verifierar full text, oförändrade innehållshashar,
individuella frågebindningar, felaktiga svar, modellbyte och avbrott av väntande
anrop. Samma nätverksförbud som resten av `research_reuse` gäller i CI.
`jev_controls.py` innehåller fem syntetiska kontrollfall, inklusive sena domslut,
rubriker, partsyrkanden, sammanblandning av två poster och motstridiga datum.
Kontrollfallen beskriver inga verkliga rättsfall.

Kör från backend med den riktiga miljökonfigurationen:

```sh
python scripts/check_jev_passages.py --live --input saved-assessment-input.json \
  --output new-jev-report.json --repeat 2 --controls
```

Indata har `need.question` och `evidence` med serialiserade `ResearchEvidence`.
Det är ett separat laboratorieläge; ingen databasanslutning öppnas och inga
researchfrågor, dokument, vektorer, TTL eller produktionsinställningar ändras.
Modell, endpoint och timeout kommer från ordinarie Jev-inställningar.
`--concurrency N` väljer uttryckligen en annan samtidighet för experimentet.
`--controls --controls-only` kör bara kontrollfallen. `--limit N` begränsar
antalet granskningsgrupper för ett inledande funktionstest.

Varianterna använder samma sex befintliga screeningfrågor:

| Variant | Underlag och frågebindning |
| --- | --- |
| `compact` | Befintlig komprimering med 280 tecken, ett anrop per post |
| `full` | Hela sparade utdraget, rättsanalysen och råtexten, ett anrop per post |
| `batched_refs` | Två hela poster i gemensamt underlag; varje fråga pekar på sitt evidens-ID |
| `batched` | Diagnostisk variant som även upprepar hela målposten i varje fråga |

Standardordningen är `compact full batched_refs`; nästa iteration kör omvänd
ordning. `--variants compact batched_refs` väljer två specifika varianter.
En grupp med två poster innehåller tolv frågor, inte två. Exakta dubbletter
grupperas med produktionens befintliga funktion och dubblettkopplingarna sparas.
Inga nya prompttexter eller alternativa modeller används.

Rapporten innehåller underlagets SHA, frågor och begärans SHA, varje anrops
status, svarad modell, rapporterade tokens och fullständiga poäng. Vid API- eller
schemafel avbryts körningen, väntande anrop avslutas och rapporten markeras
`incomplete`. Det finns inga automatiska omförsök eller ersättningsresultat.
En befintlig rapportfil skrivs inte över. `completed` betyder att mätningen
genomförts; kontrollfallens separata `checks` avgör om bedömningarna var rätt.

### Första live-experimentet 2026-10-02

79 frysta evidensposter om 36 § avtalslagen gav 77 granskningsgrupper. Samma
konfigurerade `openjev-latest`, svarad modell `openjev-0.1`, samtidighet åtta
och timeout fem sekunder användes. En komplett jämförelse gav:

| Variant | Tid | Anrop | Rapporterade indatatokens |
| --- | ---: | ---: | ---: |
| `compact` | 9,28 s | 77 | 47 132 |
| `batched_refs` | 17,07 s | 39 | 285 847 |

Nästa iteration av grupperingen avbröts med HTTP 429: åtta anrop hann lyckas,
ett gav fel och trettio avbröts. Ett tidigare fulltextexperiment vid samtidighet
åtta gav också HTTP 429. Ett separat experiment vid samtidighet ett fick
timeout i fulltextvarianten. Detta är inte stabila medianer eller bevis på att
gruppering i sig är långsammare: både textmängd och frågebindning ändras, och
hela fulltextvarianten saknar en komplett tidsmätning.

Kontrollerna kördes två gånger med samtidighet ett. Det sena domslutet missades
av `compact` båda gångerna och hittades av båda fulltextvarianterna båda
gångerna. Alla tre avvisade rubriken och partsyrkandet utan domslut. Den
optimerade grupperingen höll isär svarsstöd och rubrik även i samma anrop.
För en uttrycklig datumkonflikt flaggade den bara den andra posten i båda
iterationerna; individuella anrop saknar den andra posten att jämföra mot.
Två slumpmässigt grupperade poster ersätter inte en övergripande
motsägelsebedömning av allt tillgängligt underlag.

Full text avser allt som redan är sparat, inklusive befintliga markeringar om
trunkerade källor; experimentet återskapar inte saknade domskäl. De verkliga
77 posterna har inga manuellt granskade facit i detta experiment. Därför ger
ändrade screeningpoäng ingen mätning av juridisk träffsäkerhet eller slutlig
svarstillräcklighet. Ingen variant införs i produktion på dessa resultat.
Ett fortsatt experiment bör använda avgränsade textpassager med verifierbar
full täckning och en separat jämförelse av motstridiga fakta.

### Avgränsade passager och separata faktapar

`scripts/check_jev_windows.py` kör nästa experiment på samma frysta underlag:

```sh
python scripts/check_jev_windows.py --live --input saved-assessment-input.json \
  --output new-window-report.json --repeat 2
```

`--controls-only` kör de nio syntetiska kontrollfallen. Samtidighet och timeout
kommer från ordinarie inställningar; `--concurrency 1` väljer uttryckligen en
separat mätning med ett anrop i taget. De tre varianterna är `compact_rank`,
`excerpt_windows` och `source_windows`; `--variants` väljer en delmängd.

Här mäts endast relevans och direkt svarsstöd, med samma två befintliga
frågedefinitioner i alla tre varianter. Tiderna avser denna komponent, inte
alla sex screeningfrågor, slutlig tillräcklighetsbedömning eller en research.
`excerpt_windows` täcker hela det sparade utdraget. `source_windows` täcker
`legal_result.raw_text` för juridiskt analyserade poster och `excerpt` för
övriga poster. Det senare skickar inte den strukturerade rättsanalysen; ett
komplett textfält är inte samma underlag som föregående fulltextvariant.

Passagernas kärnor är högst 1 200 Python-tecken och täcker textfältet exakt
utan luckor eller dubblerade kärnpositioner. Bedömningens textvy innehåller
även upp till 160 tecken före och efter kärnan. Originaltexten återskapas och
verifieras före anrop; varken blanksteg, radslut, Unicode eller canonical SHA
normaliseras. Rapporten binder kärn- och kontextpositioner till originalets
text-SHA och befintliga innehållshash. Dessa är laboratoriets vyer, inte nya
ingestion-chunks eller embeddings. Varje batch håller ordinarie teckenbudget
och högst sexton frågor. En för stor passage ger fel utan avklippning.

Relevans och svarsstöd för en post hämtas från samma bästa passage. Poäng från
olika passager får inte kombineras till ett påhittat stöd. Alla passagepoäng
sparas för granskning. Detta ger svarskandidater, inte ett automatiskt beslut
om att forskningsfrågan är besvarad. Ingen beständig bedömningscache införs.

För motsägelser prövas explicit utpekade faktapar separat i båda riktningarna,
med hela målposten och hela jämförelseposten. Kontrollfallen omfattar
motstridiga aktuella datum, överensstämmande datum, historiska versioner och
olika avtal. Paret måste få plats i budgeten. Detta testar Jevs bedömning av
givna faktapar; experimentet upptäcker inte automatiskt alla relevanta faktapar
i de verkliga 77 posterna och ändrar inte Graph v2:s TTL eller invalidation.

`test_jev_windows.py` verifierar exakt rekonstruktion, källfält, budget,
frågebindningar, sammanhängande poäng, faktapar och att diagnostik bevarar
HTTP-felet samt redigerar bort API-nyckeln. Externa anrop mockas och sockets
blockeras även för dessa tester. API-fel avbryter och lämnar rapporten
`incomplete`; ingen variant används som ersättning för en annan.

#### Kort backoff vid HTTP 429

`--retry-429` aktiverar ett separat, uttryckligt experiment med begränsade
omförsök mot samma tjänst, modell och oförändrade anrop. Utan flaggan gäller
fortfarande ett försök per anrop. Produktionsklienten ändras inte.

Högst fyra HTTP-försök görs per logiskt anrop. Grundväntan mellan försöken är
0,5, 1 och 2 sekunder, med upp till 0,2 sekunders jitter. `Retry-After`, både
antal sekunder och HTTP-datum, respekteras som minsta väntan. En gemensam paus
stoppar nya anrop från experimentets klient; redan pågående anrop kan
fortfarande avslutas. Högst tjugo sekunders sammanlagd väntan tillåts per
logiskt anrop, även när ett annat parallellt anrop förlänger pausen. En längre
begärd väntan ger ett tydligt fel utan ett för tidigt omförsök. Timeout per
HTTP-försök kommer fortfarande från ordinarie inställningar.

```sh
python scripts/check_jev_windows.py --live --input saved-assessment-input.json \
  --output new-backoff-report.json --repeat 2 --concurrency 8 \
  --variants compact_rank excerpt_windows --retry-429
```

Alla väntetider ingår i variantens uppmätta tid och anropets latens.
`requests` räknar logiska anrop; `http_attempts` redovisar de faktiska
HTTP-försöken separat, tillsammans med `backoff_waits`, `scheduled_retries`,
`retry_policy` och fortsatt feldiagnostik. Väntetiderna per parallellt anrop
överlappar och ska inte summeras som total väggtid. Slutligt HTTP 429,
överskriden väntbudget, felaktig `Retry-After`, övriga HTTP-fel, timeout och
ogiltiga svar avbryter experimentet med en `incomplete` rapport.

`test_jev_backoff.py` mockar tjänsten och väntan. Testerna verifierar
oförändrad begäran, försöks- och väntgränser, båda `Retry-After`-formaten,
gemensam paus, avbrott och att latensmätningen inkluderar väntan. Inga
databasanslutningar används i detta experiment.

#### Andra live-experimentet 2026-10-02

En komplett jämförelse vid samtidighet ett och samma femsekunderstimeout gav:

| Variant | Tid | Anrop | Passager | Täckta kärntecken | Indatatokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Korta utdrag, två frågor | 61,18 s | 77 | – | – | 35 582 |
| Hela utdrag i passager | 59,35 s | 70 | 194 | 192 306 | 191 944 |
| Rå källtext i passager | 125,97 s | 141 | 349 | 376 838 | 369 178 |

Vid upprepning i omvänd ordning tog utdragspassagerna 58,68 s; den efterföljande
korta varianten avbröts med timeout. Det finns därför bara en komplett
seriemätning av den korta varianten. Råtextvarianten har inte upprepats.

Vid samtidighet åtta tog den korta varianten med två frågor 9,44 s. Den
efterföljande passagevarianten avbröts med HTTP 429 efter 51 lyckade anrop.
Ett senare isolerat prov av enbart utdragspassagerna genomförde alla 70 anrop
på 9,15 s. Det visar ungefär samma tidsordning för betydligt mer text, men
ingen säker tidsvinst eller stabil kapacitet för sammanhängande körningar.
De mindre passagerna avskaffar inte API-begränsningen. Felens exakta kvotorsak
är inte fastställd; det enstaka diagnostiska anropet gav 200 utan kvotheaders.

De nio kontrollfallen kördes två gånger. Båda passagevarianterna klarade alla
tolv märkta bedömningar av svarsstöd per variant, inklusive domslut först i
tredje passagen. Den korta varianten missade de två sena domsluten i båda
iterationerna. En separat granskning av tolv passagepoäng från det tredje
fönstret visade korrekt svarsstöd i rätt passage och avvisade de tidigare
passagerna. Faktaparsbedömningen klarade sexton av sexton riktade kontroller,
inklusive historiska förändringar och olika avtal. Ett negativt svar för olika
avtal låg nära tröskeln (0,477 mot 0,5); kontrollfallen är ingen allmän
kalibrering eller bevis på juridisk precision i de verkliga posterna.

Detta stödjer fortsatt kvalitetstest av passagebedömningen, men ingen
produktionsändring görs. Verkliga träffars riktighet, hantering av relevanta
faktapar och hållbar API-kapacitet återstår att verifiera.

#### Backoff-experimentet 2026-10-03

Med samma frysta 79 poster, 77 granskningsgrupper, modell `openjev-0.1`,
samtidighet åtta och femsekunderstimeout per HTTP-försök avslutades två
iterationer. Ordningen vändes i den andra iterationen. Väntan ingår i tiderna:

| Ordning | Variant | Tid | Logiska anrop | HTTP-försök | HTTP 429 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Korta utdrag | 9,94 s | 77 | 77 | 0 |
| 2 | Hela utdrag i passager | 28,30 s | 70 | 79 | 9 |
| 3 | Hela utdrag i passager | 19,18 s | 70 | 74 | 4 |
| 4 | Korta utdrag | 33,35 s | 77 | 86 | 9 |

Alla 294 logiska anrop lyckades efter totalt 316 HTTP-försök. Tjugo anrop
behövde omförsök; två av dem fick 429 två gånger. Högst tre försök behövdes.
Samtliga 22 svar med HTTP 429 angav `Retry-After: 5` och feltexten
`Rate limit exceeded: 60 requests per minute per key.` Det är tjänstens
uppgivna gräns, inte en oberoende verifiering av dess kvotberäkning.

Ett föregående prov med endast sex sekunders sammanlagd väntbudget lyckades
återhämta fyra anrop men avbröt nästa iteration när pausen förlängdes.
Den ofullständiga rapporten bevarades; den slutliga tjugosekundersgränsen
rymmer flera femsekunderspauser utan att göra försöken obegränsade.

Backoff möjliggjorde alltså en komplett jämförelse vid 429, men tiderna är
nu tydligt påverkade av kvoten. Resultatet visar varken stabil svarstid eller
högre juridisk precision. Alla passager och anrop behöll samma underlag;
inga alternativa modeller, kortare ersättningsutdrag eller uteblivna poster
användes för att slutföra mätningen.
