# Utvärdering av GLiNER2 och JevSpan för Socialism

**Status:** Utredning — ingen produktionsimplementation beslutad.
**Datum:** 2026-10-29. Underlag: kodinventering av denna repo, primärkällor för båda projekten
([GLiNER2-rapport](gliner2-engineering-evaluation.md), JevSpan-rapport nedan), och en avgränsad
offline-körning.

## A. Teknisk inventering — vad finns redan, vad överlappar JevSpan?

JevSpans flerstegsprocess jämförd steg för steg med Socialisms befintliga kod:

| JevSpan-steg | Socialism-motsvarighet | Överlapp | Bedömning |
|---|---|---|---|
| 1. Segmentering | `experiments/overgraph_ingest/overgraph_ingest/extraction/{docx,pdf}.py` (strukturella block: rubriker, tabeller, listor), `segmentation/` (structural-v1), `extraction/model.py::assign_canonical_offsets` (exakta offsets i kanonisk text) | **Delvis** | Vår segmentering är dokumentstruktur-medveten och starkare för avtal än JevSpans generiska menings-/klausul-delning (`segmenter.py`) |
| 2. Kandidatspann | `jev/predicate.py::candidate_spans` — "Code proposes spans. Jev only picks. It cannot generate text." (`split_predications`, labeled units, resolved references). Retrieval-kandidater: `jev/candidates.py` (frysta hybridträffar, k=50) | **Identisk begränsning** | JevSpans dokumenterade tak — "an entity that no window covers cannot be found" — gäller redan i vår kod. Det är vår svagaste punkt (g4-05). JevSpans skjutfönster (upp till 32 enheter, max 12 latinska ord) tillför inget för långa svenska sammansättningar; våra strukturspann är annorlunda men inte bättre på just detta |
| 3. JEV Choice för kandidatidentifiering | `jev/classify.py::classify_candidates` (batcherade choice-frågor), `jev/predicate.py::predicate_questions` (span-choice med "none"-kriterium), swe-gym `crates/swe-gym/src/provider.rs::HttpJevProvider` (choice + criteria) | **Helt överlappande** | Samma mekanism: choice-frågor med kriterier. Inget att hämta |
| 4. JEV-verifiering av entitetstyp | `backend/app/swe/providers.py` (research assessment Noul-frågor + `classify_research_decision`), `backend/app/jev/system.py` (`JevSystemOne`, `parse_noul`, `noul_confidence`), swe-gym providers (choice → score_bp 9500/500/4500) | **Helt överlappande** | Vår verifiering är bredare (noul + choice + confidence-sammanslagning) |
| 5. Spann-gränsjustering | `graph/verifier.py::_bound_errors` (validerar gränser mot kanonisk rekonstruktion — upptäcker, justerar inte) | **Saknas** | JevSpans `_boundary_variants` (trim/extend ±2–3 enheter + JEV-omval) är den enda teknik vi inte har. Liten, kopierbar idé |
| 6. Överlapp/upprepade omnämnanden | `ids.py` (dedup på kanoniska offsets), `doctags`; JevSpans propagate-steg (dokumentomfattande ytforms-sökning) | **Delvis** | Propagate är ett rimligt recall-komplement, trivialt att återskapa mot våra TextUnits |
| 7. Entiteter + offsets + scores + beslutsspår | `ExtractedBlock` (BBox + offsets), `JevUsage`/`raw`, swe-gym fixtures (råa svar sparas) | **Helt överlappande** | Redan täckt |

**Slutsats A:** JevSpan som helhet är ett parallellt NER-system över en JEV-klient vi redan har
(steg 3–4, 7 är våra egna). De enda delar som *inte* finns hos oss: (5) boundary-refinement och
(6) propagate. Båda är små, välavgränsade idéer. **Att införa hela JevSpan är inte motiverat.**
Samtidigt bekräftar JevSpans egen dokumentation precis vår svagaste punkt: kandidatgeneratorn är
taket. Ingen av våra generatorer (strukturspann, predikatdelning) föreslår *lärt* genererade
entitetsspann — och det är där GLiNER2 kommer in.

## B. Projektutvärdering

### B.1 GLiNER2
- **Vad:** schema-konditionerad encoder: zero-shot NER, klassificering, strukturerad extraktion,
  relationer, span-attribut — en forward-pass. Två arkitekturer: span (max ~12 ord) och
  **boundary (GLiNER2.5, obegränsad spannlängd i 4 096-ord-fönster)** — det senare är direkt
  relevant för långa juridiska uttryck.
- **Checkpoints:** 74M–340M, alla vikter Apache-2.0 (kommersiellt bruk tillåtet; koden Apache-2.0).
  **Svenska: ingen checkpoint listar svenska, inga svenska benchmarks finns.** Encodern
  (mDeBERTa-v3-base, CC100, 100 språk inkl. svenska) gör zero-shot svenska plausibel men
  **overifierad** — måste benchmarkas lokalt.
- **Körning:** CPU-först, ingen GPU krävs; ~0.3 s per ~4 000 tecken på CPU (community-mätt);
  287M-modellen ≈ 594 MB FP16. Ingen officiell ONNX (öppen issue), fp16 + torch.compile.
- **Hälsa:** 2 426 stjärnor, senaste push 2026-10-20, v2.1.0 2026-10-09. Kända kvalitetsissues:
  relationer delvis trasiga (#101), långdokument-bugg (#137). Svensk sammansättning: whitespace-
  tokenizern behåller sammansatta ord hela — ingen känd svensk-specifik issue.
- Fullständig rapport med källor: [docs/gliner2-engineering-evaluation.md](gliner2-engineering-evaluation.md).

### B.2 JevSpan
- **Vad:** zero-shot NER-pipeline över TypeSafe JEV (choice-frågor). Sjustegsprocessen enligt ovan.
- **Resultat:** 73.7 medel-strict-F1 på 12 kinesiska/engelska NER-set — författarens egna körningar,
  ingen peer review, **ingen svensk eller juridisk utvärdering; språk explicit zh/en**.
- **Licens/beroenden:** MIT; fastapi/httpx/python-dotenv/uvicorn. **Hälsa: skapat 2026-09-27,
  sista commit 2026-09-28, 10 stjärnor, en författare — färskt, inaktivt, obevisat.**
- **Begränsningen (exakt citat, README "Limitations"):** "Spans come from the segmenter. Jev only
  scores candidates, so an entity that no window covers cannot be found."
- **Ingen relationsextraktion, ingen entity linking** — bara spann + typ.

### B.3 Den kombination användaren pekade på
GLiNER2:s lärda kandidatspann + vår befintliga JEV-verifiering (steg 3–4 ovan) **utan** JevSpans
infrastruktur. Det fyller exakt det gap inventeringen fann: kandidatgeneratorn. JEV behöver
spann för att verifiera; GLiNER2 föreslår spann oberoende av formulering. Inget nytt NER-ramverk,
ingen ny JEV-klient, ingen parallell pipeline.

## C. Experimentdesign

**Hypoteser:**
- H1: GLiNER2.5-multi zero-shot hittar entitetsspann i svenska avtalsklausuler som vår
  deterministiska extraktor missar (särskilt avgångsvederlag, ansvarstak, undantag).
- H2: GLiNER2-spann + befintlig JEV-verifiering ger högre strict-span-F1 än JEV ensam på
  samma chunkar, till lägre kostnad än JevSpans skjutfönster-approach.
- H3: (fine-tuning, separat experiment) domänfinjustering reducerar JEV-verifieringsbehovet
  mätbart utan överanpassning.

**Data:** frysta `golden_v4`-chunkar + `action_market/states.txt` + ett separat testset med nya
avtalsformuleringar (nästa steg — får inte blandas med g4).

**Tre skilda uppgifter (blandas aldrig):**
1. **NER:** rätt entitet + exakt spann (strict span P/R/F1).
2. **Relationer:** rätt entitet kopplad till rätt roll/villkor/värde (relation P/R).
3. **Evidensrelevans:** förstår systemet varför klausulen behövs för frågan (SWE answer
   correctness — g4-utvärderingen).

**Mått:** strict span P/R/F1, entity linking accuracy, relation P/R, FN/FP, confidence-kalibrering
(scores vs faktisk korrekthet), JEV-anrop (marginalkostnad), CPU-tid/latens, SWE answer
correctness. Kandidatfel/behovsfel/svarsfel separata. Facit enbart i utvärderingen.

**Jämförelsearmar (samma frysta underlag):**
- Arm 0: befintlig extraktor (deterministisk + selektiv JEV) — baseline.
- Arm A: GLiNER2 som primär extraktor, JEV vid osäkerhet.
- Arm B: GLiNER2-spann + befintlig JEV-verifiering (hybriden; inget JevSpan).
- Arm C: GLiNER2 + JevSpan som oberoende upptäcktsarm (endast om B motiverar det).

## D. Experimentresultat (avgränsad offline-körning)

Körd: `fastino/gliner2.5-multi-v1` (boundary-arkitektur, zero-shot, inga svenska etiketter i
träningsdatan), isolerad venv (`/tmp/gliner_venv`, ingen produktionspåverkan), 8 frysta
g4-evidenschunkar, svenska etiketter. Skript: `crates/swe-gym/tools/eval_gliner.py`; resultat:
`crates/swe-gym/benchmarks/gliner_spans.json`.

| Mått | Värde |
|---|---|
| Strict span precision | 0.28 |
| Strict span recall | **0.70** |
| Strict span F1 | 0.40 |
| TP / FP / FN (distinkta spann) | 7 / 18 / 3 |

**Tolkning (ärligt):** zero-shot hittar de juridiska kärnspannen — alla fyra tidsvärdena
("sex (6) månader", "tolv (12) månader", "tre (3) månader" ×2), "avgångsvederlag" och
"omedelbar verkan" — recall 0.70. Men precisionen är låg (0.28): 18 falska positiva med
generiska etiketter (parter, datum, rubriker övertriggras). Det är exakt den profil som gör
hybriden rätt: **GLiNER2 som spann-förslagsgivare (recall), befintlig JEV som verifierare
(precision)** — de spann som ska verifieras är i praktiken just de som GLiNER2 hittar, medan
JEV redan bevisat 0.92–0.95 precision på verifieringssidan (§27).

**Kända mätbegränsningar:** denna API-nivå returnerar spann som strängar utan offsets och
confidence — offset-/kalibreringsmätning kräver boundary-extraktorns råa API (nästa steg).
Modellen dubbelrapporterade ett spann (känt issue #137). Inga tränings-/testdokument överlappar
g4-facit.

**Miljönot:** körningen krävde torch (CPU) + transformers + gliner2 i en separat venv —
~1 GB nedladdning, ~1 s/chunk på CPU. Ingen ändring av produktionsberoenden.

## E. Arkitekturrekommendation (preliminär, givet A–C)

1. **Behåll befintlig implementation** som baslinje och som verifieringsskikt.
2. **Komplettera kandidatgeneratorn med GLiNER2-spann** — hybriden i B.3 — som en isolerad,
   avstängbar spann-förslagsgivare vars utdata går in i den befintliga selektiva JEV-verifieringen
   med `verification_status: "CANDIDATE"` (illustrativt kontrakt i specen; vi har redan
   TextUnit-id + offsets + raw-trace i befintliga strukturer — ingen ny datamodell).
3. **Återanvänd max två JevSpan-idéer om D visar värde:** boundary-refinement (trim/extend-varianter
   + JEV-omval) och propagate (ytforms-sökning över TextUnits). **Inte** JevSpan som paket.
4. **Fine-tuning:** separat experiment, JEV/GLiNER-etiketter som granskade kandidater, aldrig
   automatiskt facit; tränings-/testdokument åtskilda; golden-testsetet orört.
5. **Oförändrat:** SWE:s fyra lager, operationsgrinden, ingen RL, ingen produktionsingest.
   En NER-confidence får aldrig ensam kringgå ett operationskontrakt eller markera ett behov
   som RESOLVED.

**Acceptanskriterier** (specens §10): 1–2 täcks av A–B ovan; 3 av C; 4–5 av C+D; 6 av E —
med slutgiltig rekommendation villkorad av D:s mätvärden.

## D2. Fyra-armars-experimentet (30 oberoende chunkar)

Testset: `benchmarks/gliner_testset.json` — 30 chunkar, 38 guldspann, behovsstyrda etikettspecar.
Guldspannen är deterministiskt härledda (samma mekanism som den befintliga generatorn) — **den
viktiga mätningsreservationen**: arm 0 mäts därför mot sitt eget facit, och "unik täckning" kan
inte avgöras på detta guld.

| Arm | Precision | Recall | F1 | tp/fp/fn |
|---|---|---|---|---|
| 0: befintlig generator | 1.00 | 1.00 | 1.00 | 33/0/0 |
| 1: GLiNER2 generella etiketter | 0.15 | 0.48 | 0.23 | 16/89/17 |
| 2: GLiNER2 **behovsstyrda** etiketter | **0.30** | 0.42 | 0.35 | 14/33/19 |
| 3: union → JEV-verifiering | 0.50 | 1.00 | 0.67 | 33/33/0 |

**Slutsatser:** (1) behovsstyrningen **dubblar precisionen** (0.15 → 0.30) mot generiska
etiketter med måttligt recall-tapp (0.48 → 0.42) — granskningens hypotes bekräftad i riktning.
(2) Unionen ger recall 1.00 men ingen unik täckning på detta guld — eftersom guldet är
deterministiskt härlett. **Unik täckning kräver guldspann bortom den deterministiska extraktorns
räckvidd** (omskrivna riskklausuler utan nyckelord) — nästa steg, inte mätt ännu.

**g4-05 med GLiNER2-spann (det konkreta testet):** med behovsstyrda etiketter levererar GLiNER2
kandidatspannen "avgångsvederlag" (chunk 19) och "sex (6) månader" (chunk 18) — **2 av de 3
saknade riskklausulspannen** som fällde g4-05. Chunk 20 ("omedelbar verkan") spannades inte
denna körning. Det är en verklig, partiell lösning av en verklig begränsning — men 1/3 kvarstår,
och det är precis vad nästa körning ska mäta med exakta offsets.

## D3. Utmaningssetet: unik täckning, verifieringsöverlevnad, uppgiftsnytta

50 manuellt annoterade klausuler (25 korpus + 25 omskrivna formuleringar utan nyckelord),
76 guldspann, annoterade oberoende av regex och GLiNER2 (agent-författade, granskningsbara —
proveniens protokollförd i `benchmarks/gliner_challenge.json`).

| Mätning | Resultat |
|---|---|
| 1. Unik kandidat-recall | **6/76** korrekta spann som generatorn missar |
| 2. Verifieringsöverlevnad | **6/6** unika spann godkända av JEV |
| 3. Faktisk uppgiftsnytta | **25/50 → 29/50** behov lösta med GLiNER2 tillagd |

Diagnos per guldspann: 55 fullständiga fynd, 21 candidate-generation gap, **0
verification gap**. De unika spannen avvisas alltså inte av verifieraren — felet ligger
uppströms i kandidatgenereringen, precis där hybriden sätter in.

**Den avgörande frågan är nu besvarad:** GLiNER2 tillför information som Socialisms befintliga
generator inte hittar (6 korrekta spann), dessa överlever JEV-verifieringen (6/6), och fyra
tidigare olösta REQUIRED-behov blir lösta (25 → 29 av 50). Bidraget är marginellt, mätt och
verkligt — inte en dominerande ersättning. Kostnaden: en CPU-inferens per klausul (~1 s) +
sex JEV-verifikationer. g4-05-statusen kvarstår som tidigare: 2 av 3 spann är diagnostiska
tecken, inte ett löst behov — utmaningssetets siffror är nu det primära underlaget.

## D4. Fixtur, unika identiteter — och verifierarens diskriminering mätt

**Bevarandekravet verkställt:** utmaningssetet har nu unika `case_id` (50) och `span_id` (81
separata annoterade förekomster — inga normaliserade textnycklar). Regressionstester
(`tools/test_challenge.py`) verifierar identiteterna och fixturformatet. Varje JEV-verifikation
fryses med kandidat, klausul, prompt-version, modell, utslag, score och tidsstämpel i
`benchmarks/jev_span_fixtures.json` — omräkningar återanvänder frysta svar deterministiskt
(130 nya anrop denna körning; framtida körningar av samma utvärderingslogik betalar inget).

**Och körningen avslöjade det granskningen befarade:** med en generell span-prompt
("utgör spannet ett juridiskt sakförhållande?") godkänner JEV **50 av 50 icke-guldspann** —
verifieraren diskriminerar inte alls på denna formulering. Det förändrar tolkningen av den
tidigare 6/6-överlevnaden: de unika spannen godkändes, men det gjorde allt annat också.
**JEV:s verifieringsprecision är därmed fortfarande inte bevisad — den är nu mätt, och den är
~0 med en generell prompt.** Slutsatsen: verifieringen måste vara behovsspecifik
("utgör spannet en uppsägningstid?" med det aktuella behovets faktatyp), exakt som
behovsstyrningen gjorde för GLiNER2. Fixturens prompt-versioner gör att nästa körning lägger
till de behovsspecifika svaren utan att betala för de redan frysta.

**Strategijämförelsen (samma kostnadsdefinition, alla anrop räknade):** S1 (GLiNER2 överallt)
50 inferenser + 140 JEV-anrop; S2 (GLiNER2 endast vid kvarstående gap) 25 inferenser + 44
JEV-anrop — **halva kostnaden för samma täckning**, vilket stödjer S2 som favorit. Men båda
siffrorna är villkorade av verifierarens bristande diskriminering och ska inte ligga till grund
för något beslut innan den behovsspecifika verifieringen är mätt.

## D5. Verifieringsarmarna: behovsspecifik JEV diskriminerar — med uppmätt avvägning

Fyra armar över samma frysta kandidatpopulation (129 spann: GLiNER2-kandidater + guldspann +
svåra förväxlingsdistraktorer), endast prompten ändrad. Nya promptversioner lades till i
fixturen; den generella armens svar återanvändes (1 nytt anrop), resten nya (388 totalt).

| Arm | Unik recall | FP | Precision | FRR | Lösta behov |
|---|---|---|---|---|---|
| A generell | 27/27 | 49 | 0.68 | 30 | 50/50 |
| B behovsspecifik | 24/27 | 21 | 0.76 | 17 | 47/50 |
| C behovsspecifik + kontext | 25/27 | 24 | 0.75 | 19 | 48/50 |
| D behovsspecifik + **kontrast** | 22/27 | **16** | **0.79** | **14** | 45/50 |

**Preciseringen bekräftad:** den generella armens precision är 0.68, inte 0 — 100 % FP på
negativa betyder inte noll precision totalt, eftersom populationen innehåller många positiva.

**Slutsatserna:** (1) behovsspecifik verifiering **diskriminerar** — FP 49 → 16, precision
0.68 → 0.79, och de kontrastiva reglerna (per begreppstyp, inte per golden-fall) ger bäst
precision och lägst FRR. Hybridens två komponenter fungerar nu tillsammans: GLiNER2 upptäcker,
JEV avgör om fyndet uppfyller det specifika behovet. (2) **Avvägningen är mätt:** striktare
verifiering kostar 5 unika fynd (22/27) och 5 lösta behov (45/50) — recall-vinster köps inte
längre gratis. (3) **FRR halverades men är inte noll (14):** granskningens målbild "helst 0" är
inte nådd — verifieringsuppgiften blandar fortfarande entitetstyp och evidensrelevans.

**Beslutet enligt granskningens ram:** kompensera inte med fler JEV-anrop — dela upp
verifieringen i stegen **entitetstyp → relation → evidensrelevans** (går in i den befintliga
behovsstatuskedjan DISCOVERED → SUPPORTED → RESOLVED, utan nya lager). Nästa isolerade
experiment mäter den uppdelningen över samma frysta population.

## D6. Stegvis verifiering (E/F/G): typ → relation → relevans, med nedfallslogg

Samma frysta population; arm D kvar som jämförelse. Varje kandidats nedfallspunkt loggas.
Falskt RESOLVED räknas per unikt `need_id`: ett behov vars lösning skulle använda ett
felaktigt värde (fel-typ-spann godkänt) — inte bara ett godkänt spann som råkar mappas.

| Arm | Unik recall | Precision | FP | Rätt lösta | **Falskt lösta** | Nedfall (typ/rel/relevans) |
|---|---|---|---|---|---|---|
| D (jämförelse) | 22/27 | 0.79 | 16 | — | 14 (gammal def.) | — |
| E full JEV-kedja | 16/27 | 0.67 | 16 | 26 | **13** | 10 / 0 / 1 |
| F det-typ + JEV-rel | 16/27 | 0.65 | 23 | 23 | **16** | 10 / 1 / 0 |
| G max-deterministiskt | 2/27 | 0.61 | 12 | 19 | **8** | **25** / 0 / 0 |

**De viktigaste fynden:**

1. **Nedfallsloggen pekar ut typsteget som recall-flaskhalsen** — 10 av 27 unika fynd dör i
   typsteget (E/F), 25 i G. Relation och relevans dödar nästan ingenting (0–1). Förlusten
   sitter alltså inte i den semantiska bedömningen utan i entitetstypsbestämningen.
2. **Granskningens målbild är inte nådd:** inget steg uppnår D:s 45 lösta behov, och falskt
   lösta förbättras bara marginellt (13–16) utom i G — som köper sina 8 med 26 färre lösta
   behov. Avvägningen är mätt och ärlig: striktare kedjor betalar i recall.
3. **Överraskningen — och en precisering av det återkommande mönstret:** F slog inte E.
   Den deterministiska typdetektorn är sämre än JEV på omskrivna tidsuttryck ("ett kvartal",
   "ett halvt år") — 10 unika fynd föll i typsteget just där. Mönstret från SWE-serien
   preciseras: JEV är mest värdefull för det smala semantiska beslut vanlig kod *inte*
   redan kan fatta — och entitetstyp för omskrivna juridiska uttryck är ett sådant beslut,
   medan relationen (när kontexten är entydig) kan avgöras deterministiskt.
4. **Nästa kandidat till typsteget:** GLiNER2:s egna etiketter — kandidaterna bär redan
   GLiNER2:s typ, som inte begränsas av regex. Att använda den som typsignal skulle ta bort
   både regex-taket och JEV-typ-anropen. Nästa arm testar det.

**Kostnad:** 272 nya JEV-anrop totalt över E/F/G (E tyngst med hela trestegskedjan); omkörningen
efter fixturen kostade 0 anrop — deterministisk omräkning fungerar.

## D8. De 14 falskt lösta — undersökta, klassificerade

**Metodfrågan besvarad:** grupperna är ömsesidigt uteslutande (0 behov i båda). Nyansen
protokollförd: alla 14 har sina guldfakta godkända — risken är att slutsatsen använder ett
felaktigt godkänt spann, inte att fakta saknas.

**Felklasserna (arm D:s 14 falskt lösta):**

| Klass | Antal | Hantering |
|---|---|---|
| **Gräns-artefakt** (samma faktum, bara brackets/whitespace: "[nio (9)] månader" vs "nio (9) månader") | **8** | Determininistisk spann-normalisering — inte ett verifieringsfel alls |
| Typkrock (datum/part godkänt för tidsperiodsbehov) | 3–4 | Deterministisk typkontroll i kontraktet |
| Korrekt faktum som inte räcker (äkta irrelevanta fakta: datum, belopp, "ersättning") | 3–4 | JEV:s semantiska osäkerhet — mätbar, hanteras av operationens entydighetskrav |

**Beslut 2 får sin första data:** ~8 av 14 är inte verifieringsfel utan **kontraktsfel**
(normaliseringen som redan finns i corpus-pipelinen användes inte i utvärderingen); ~4 fångas
av en deterministisk typkontroll i behovskontraktet; **~3–4 är äkta JEV-semantisk osäkerhet**.
Enligt granskningens regel rättar vi kontraktet — ingen ny modell — och accepterar den
återstående mätbara osäkerheten, som operationens befintliga entydighetskrav (flera
motstridiga värden → INSUFFICIENT_EVIDENCE) redan är byggt för att hantera.

**Frysning:** GLiNER2/JEV-kombinationen fryses här: befintlig generator + GLiNER2 föreslår
spann (typer godkänns aldrig automatiskt), JEV arm D gör det enda behovsspecifika kontrastiva
beslutet, och SWE:s evidens- och operationskontrakt härleder behovsstatus. Nästa experiment:
falskt RESOLVED med det rättade kontraktet (normalisering + typkontroll), inte fler modeller.

## D9. Efterbehandlingsarmarna — och ytterligare ett guld-fynd

Samma frysta population och JEV-beslut; endast kontraktets efterbehandling ändrad
(A nuvarande / B + kanonisk spann-normalisering / C + behovsspecifik typkontroll /
D + entydighet). Under körningen hittades och åtgärdades **ytterligare två guld-defekter**:

1. **Bracket-buggen i guld-generatorn:** `str.strip("[]")` lämnade interna "]"-tecken
   ("nio (9)] månader") — de åtta "gräns-artefakterna" från D8 var delvis guld-fel, inte
   verifieringsfel. Fixad (alla brackets bort); guld regenererades och de nya spannen
   verifierades (16 nya frysta svar).
2. **Typ-överbreddhet i korpus-guldet:** korpusklausulernas guldspann ärvde generatorns
   etikettlogik — "tre (3) år" i en uppsägningsklausul märktes som NOTICE_PERIOD trots att
   det är en förlängningsperiod. JEV avvisade den korrekt (NO) — guldet var fel, inte
   verifieraren. Fix (relationsmedveten guldtypning) är identifierad och är nästa steg
   innan slutsiffrorna kan läsas slutgiltigt.

**Dagens arm-siffror (med kända guld-fel kvar):** alla fyra armar visar samma 5 överlevare —
C:s typkontroll och D:s entydighet är inerta på dem eftersom deras kontraktstyper är ANY och
inga konflikter finns. Överlevarna är de äkta semantiska grannarna:

| Fall | Felaktigt godkänt | Kan påverka ett svar? |
|---|---|---|
| g5-01 [Avtalspart] | "hyresgästen" (roll, inte partsnamn) | **Ja** — svaret kan namnge en roll i stället för en part |
| g5-04/45 [Belopp] | "kronor" / "sjuttiofem tusen kronor" (generiskt/fel belopp) | Ja — fel belopp i slutsatsen |
| g5-10 [Datum] | "2023-02-01" (fel datum) | Ja — fel datum |
| g5-47 [Ersättning] | "ersättning" (generisk term) | Möjligen — underbestämt svar |

**Svaret på milstolpefrågan i sin första form:** efter att guld-defekterna räknats bort
återstår **fem behov där ett semantiskt felgodkännande kan passera grinden och påverka ett
svar** — inga av dem fångas av dagens deterministiska kontrakt (typ ANY, inga konflikter).
Det är JEV:s återstående semantiska osäkerhet, mätbar och ärligt redovisad. Nästa steg:
rätta guldtypningen, köra om armarna, och därefter följa de fem fallen genom SWE:s
operationsgrind till faktiska svar — exakt den fråga granskningen satte som nästa milstolpe.

## D10. Guldgranskning v3 och svarskontaminationen

**Guldgranskningen (separat, frusen med version och proveniens):** sju korpusfall läste
generatorns etikettlogik fel — förlängnings- och avtalstidsperioder märktes som NOTICE_PERIOD.
Granskningen läser klausulen och behåller endast uppsägningsspannet i guldet; de övriga
perioderna är fel-typ-distraktorer. Efter rättelsen läser JEV:s NO-svar på "tre (3) år" som
**korrekta avvisanden** — facit var felet, inte verifieraren. Granskningen är oberoende av
både regex-generatorns och JEV:s beslut (agentgranskning, protokollförd i
`gold_review`/`provenance`).

**Överlevarna efter rättelsen är oförändrat fem — och nu följda genom operationsgrafen med
fyra separata händelser:**

| Fall | (1) felaktigt RESOLVED | (2) passerar kontrakt | (3) slutsats påverkad | Klass |
|---|---|---|---|---|
| g5-01 PARTY | ja | ja | **ja** | generell: partsroll ≠ juridisk person → typat kontrakt |
| g5-04 MONEY | ja | ja | **ja** | generell: belopp ska vara fullständigt värde → typat kontrakt |
| g5-10 DATE | nej (evidenskontamination utan behovsupplösning) | ja | **ja** | semantiskt: operativt datum → JEV |
| g5-45 MONEY | ja | ja | **ja** | semantiskt: operativt belopp → JEV |
| g5-47 ERSÄTTNING | ja | ja | **ja** | semantiskt: generisk term vs konkret åtagande → JEV |

**Svarskontamination: 5/5** — alla fem kan förvandla ett i övrigt korrekt underlag till en
felaktig slutsats (kontrollfallet med enbart guldevidens ger rätt svar i samtliga).
Klassdelningen svarar på granskningens fråga: **2/5 är generella regler som hör hemma i det
typade evidenskontraktet** (en partsroll identifierar inte ensam en juridisk person; ett
belopp måste vara ett fullständigt värde), **3/5 är juridisk betydelse som JEV eller en
annan semantisk verifierare måste bära**. Inga specialregler för de fem exemplen — reglerna
är klassformulerade.

**Milstolpen nådd i sin första form:** vi mäter nu **answer contamination**, inte bara
felklassificering — fyra händelser per fall, med kontrolljämförelse, helt offline från de
frysta svaren. Nästa steg: införa de två kontraktsreglerna, köra om, och följa de tre
semantiska fallen till slutsatser där JEV:s osäkerhet redovisas i stället för att döljas.

## D11. Trestegstillstånden och avvägningen — öppet redovisad

`VERIFIED` / `AMBIGUOUS` / `REJECTED` implementerade som en utökning av evidensobjektens
verifieringsresultat (ingen ny abstraktion), med AMBIGUOUS härlett från **observerbara
signaler** — flera distinkta operativa värden, generisk-vs-specifik form, saknad relation —
aldrig från facit. De två generella kontraktsreglerna (partsroll ≠ juridisk person; belopp
måste vara ett fullständigt värde) införda utan språkmodell. Återspelning av alla 50 frysta
fall, noll nya modellanrop:

| | Korrekt | Kontaminerad | Avstod |
|---|---|---|---|
| Före (nuvarande kontrakt) | 25 | 7 | 18 |
| Efter (trestegskontrakt) | 25 | **5** | 20 |

**Avvägningen, öppet:** 2 kontaminerade slutsatser borttagna (g5-01 partsroll-regeln; g5-04
ofullständigt belopp → avstod), **1 tidigare korrekt slutsats blockerad** (g5-36 — behovsnivå-
AMBIGUOUS övertriggade på ett datumfall; en falsk-AMBIGUOUS att kalibrera). De fem kvarvarande
"kontaminerade" granskades manuellt: två är **spann-granularitetsskillnader** (samma faktum i
kortare spann — inte semantiska fel), och de verkliga semantiska restfallen är **2–3**:
fel operativt belopp (g5-45) och generisk term som konkret åtagande (g5-47). På dem finns
**ingen observerbar signal** som skiljer det operativa värdet — det är gränsen för
signalhärledd AMBIGUOUS, och där måste JEV:s semantiska bedömning bära ansvaret med
osäkerheten följande evidensobjektet in i operationen.

**Slutsatsen enligt granskningens skärpning:** målet var att förhindra evidenskontamination
utan att förlora korrekta svar i onödan. Resultatet: 2 kontaminationer bort, 1 över-block —
avvägningen är nu synlig i en tabell i stället för dold. Nästa steg: kalibrera behovsnivå-
AMBIGUOUS (multiplicitetströskeln), följa g5-45/g5-47 med osäkerheten kvar på evidensobjektet,
och mäta samma avvägning på det större oberoende testsetet.

## E2. Rekommendationen, omformulerad per beslut

**Utvärdera GLiNER2 som en behovsstyrd, valbar kandidatgenerator i SWE:s Investigation-lager** —
där den kompletterar befintlig extraktion och återanvänder den selektiva JEV-verifieringen. Vi
bestämmer inte i förväg att GLiNER2 alltid ska köras: SWE:s informationsbehov avgör både *vilka
etiketter* den letar efter och *när* den kallas in (vid kvarstående REQUIRED-behov efter den
billiga deterministiska första undersökningen). Parallellkörning med befintlig generator förblir
möjlig när recall väger tyngre än lägsta kostnad — vilken strategi som är bäst avgör mätningen.
Ingen fine-tuning innan behovsstyrningen och den unika täckningen är mätta på ett större,
oberoende testset med guld bortom regex-räckvidden.
