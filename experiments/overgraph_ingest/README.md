# OverGraph document ingest and retrieval

Standalone experiment: extract PDF/DOCX, keep structure, write `Collection` /
`Document` / `Structure` / `TextUnit` nodes to a dedicated OverGraph database,
then measure retrieval quality. Does not import Socialism backend code or touch
`backend/data/overgraph/`.

Phase 1 (ingest performance) is closed. Phase 2 measures **search quality
before search performance**: dense, sparse, and hybrid retrieval against a
gold query, plus an exhaustive ranking so misses can be classified.

## Setup

```bash
cd experiments/overgraph_ingest
uv sync
```

## Ingest one corpus

```bash
uv run overgraph-ingest \
  --input ./data/corpus \
  --db ./data/overgraph-data \
  --dense-dimension 8 \
  --benchmark \
  --output ./data/benchmark.json
```

Generate a synthetic Swedish contract corpus (10 / 50 / 200) then ingest:

```bash
uv run overgraph-ingest \
  --generate-corpus 200 \
  --input ./data/corpus \
  --db ./data/overgraph-data \
  --dense-dimension 8 \
  --benchmark \
  --output ./data/benchmark.json
```

`--dense-dimension` is required when creating a new database. Reopening an
existing catalog reads the dimension from `manifest.current`. After ingest,
`--verify` reopens the database and checks that every published document still
reconstructs from the stored TextUnits.

## Quality gold set

The bundled gold set is **synthetic**. It encodes expected clauses, reading
order, tables, exclusions, and page spans. That is enough for regressions. It
is not a substitute for real contracts.

```bash
uv run overgraph-ingest --db ./data/overgraph-data --dense-dimension 8 --gold \
  --gold-dir ./data/gold/synthetic \
  --output ./data/gold-report.json
```

Drop real PDFs/DOCX files in a local directory (gitignored) and optionally add
a sidecar `name.json` fixture with the same fields as the synthetic fixtures:

```bash
uv run overgraph-ingest --db ./data/overgraph-data --gold \
  --gold-dir ./data/gold/synthetic \
  --real-gold ./data/gold/real \
  --output ./data/gold-report.json
```

Unscored real files still get reconstruction and coverage checks. Extraction
errors and segmentation errors are counted separately.

## Measurement suite

Runs A–F, a gold evaluation, and OverGraph batch sizes 100 / 500 / 1 000 /
5 000. Each performance cell is repeated `--repeats` times (default 5). A–D
and F use a new database per repeat. E reuses the last C database.

| Test | Documents | Cache | Database |
|---|---:|---|---|
| A | 10 | Cold | New |
| B | 50 | Cold | New |
| C | 200 | Cold | New |
| D | 200 | Extraction cached | New |
| E | 200 | Cached | Same as last C |
| F | 200 | Prepared nodes/edges | New |

```bash
uv run overgraph-ingest \
  --suite \
  --generate-corpus 200 \
  --input ./data/corpus \
  --db ./data/overgraph-data \
  --dense-dimension 8 \
  --repeats 5 \
  --output ./data/suite.json
```

For a faster smoke of the same matrix:

```bash
uv run overgraph-ingest \
  --suite \
  --generate-corpus 10 \
  --repeats 1 \
  --input ./data/corpus \
  --db ./data/overgraph-data \
  --dense-dimension 8 \
  --output ./data/suite-smoke.json
```

Graph-only write of an already prepared corpus:

```bash
uv run overgraph-ingest \
  --graph-only \
  --input ./data/corpus \
  --db ./data/graph-only \
  --cache-dir ./data/extract-cache \
  --dense-dimension 8 \
  --benchmark
```

The JSON headline is the table we optimize against later: extraction,
segmentation, construction, OverGraph writes, `end_ingest()`, `sync()`,
coverage, RAM, and database size. Node/edge throughput is reported both for
batch API calls and with finalization included.

## Official sequential baseline

Phase 1 performance is closed against this sequential run of 100 real Swedish
DOCX contracts. Later extraction parallelism or OverGraph writer changes should
compare against it, not against a new cold run.

| Mätvärde | Baseline |
|---|---:|
| Dokument | 100/100 published |
| Total tid | 2,853 s |
| Dokument/sekund | 35,1 |
| Tecken | 399 936 |
| TextUnits | 2 357 |
| Noder / kanter | 4 914 / 11 472 |
| Extraktion | 2,210 s (77,5 %) |
| OverGraph-skrivning | 0,260 s |
| `end_ingest()` | 0,182 s |
| Peak RAM / databas | 169 MB / 8,55 MB |
| Texttäckning | 100 %, 100/100 rekonstruerade |

The frozen snapshot lives at
`baselines/phase1-sequential-100-docx.json`. That run used
`structural-v1` clause labels (`1`, `1.1`, … only). Avtal 12 and Avtal 70
published and reconstructed, but their `Del A` / `A1` headings were not
stamped as clauses. That gap is recorded in `zero_clause_documents`.

## Structure labels

Headings come from document formatting first: DOCX `Heading` styles, then
larger fonts or short all-caps lines. Clause numbers are then read from the
heading text with one outline family:

- numeric: `1`, `1.1`, `2.1.1`
- part labels: `Del A`, `Bilaga 1`
- letter + number: `A1`, `B10`

Table cells are not promoted to headings. A lettered list marker such as
`a)` is not a clause. 100 % text coverage still does not mean 100 % correct
structure; Avtal 12 and 70 are the regression for the part/letter family.

## Phase 2: embeddings and retrieval quality

Do not reuse the phase-1 extra-overgraph catalog. It is locked to dense
dimension 8. Create a new database with the dense model dimension.

| Encoder | Implementation | Role |
|---|---|---|
| Dense | OpenAI `text-embedding-3-large` (3072) | Semantic search, same model as Socialism knowledge |
| Sparse | `lexical-tfidf-hash-v1` (stemmed Swedish unigrams + bigrams, hashed TF-IDF) | Lexical baseline, not SPLADE/BGE-M3 |
| Hybrid | OverGraph `reciprocal_rank` | Fusion of the two rankings |

The measured gold query is
`Vilka avtal innehåller bestämmelser om automatisk förlängning?`
in `retrieval_gold/auto-renewal.json` (20 relevant contracts, Avtal 15 as a
hard negative). A good result is document coverage, not only a high first hit.

The same engine has a gold suite in `retrieval_gold/index.json` for
notice periods, liability caps, confidentiality, and a multi-clause
secrecy carve-out. `liability-cap` and `liability-secrecy-carveout`
were corrected after the first C@8 generalisation run: passage gold is
the operative TextUnit; document gold is the contract that contains at
least one such unit. Those two lists are not the same question.

Hybrid remains the measured auto-renewal candidate baseline. It is not
the default for every question. Dense beats hybrid on confidentiality
(R@50 69 % vs 46 %). A union of dense and hybrid must be compared at a
fixed candidate budget of 50, not only as an unbounded pool.

Ingest, embed sequentially, then score dense / sparse / hybrid at several `k`.
`--embed` writes vectors and `flush()`es before search. There is no embedding
cache and no parallel encoder.

```bash
uv run overgraph-ingest \
  --input ./data/extra_corpus \
  --db ./data/extra-overgraph-phase2 \
  --cache-dir ./data/extra-cache \
  --collection extra-corpus \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --retrieve-gold ./retrieval_gold/auto-renewal.json \
  --embed \
  --output ./data/retrieval-auto-renewal.json
```

If the phase-2 database already exists, skip `--input` and only embed/search:

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --retrieve-gold ./retrieval_gold/auto-renewal.json \
  --embed \
  --output ./data/retrieval-auto-renewal.json
```

Tests and dry runs use `--dense-model hashed-dense-v1` (dimension follows
`--dense-dimension`). That is not a substitute for the OpenAI measurement.

Each strategy reports Recall@k, Precision@k, document coverage, and a miss
taxonomy against an exhaustive in-process ranking of every TextUnit:

| Klass | Betydelse |
|---|---|
| `absent` | Gold-spanen finns inte i grafen |
| `unretrieved` | Finns i grafen men saknas i motorns topp-k även när uttömmande rank ≤ k |
| `low_rank` | Finns, men uttömmande rank ≤ k och motorn placerar den utanför k |

## Frozen classify decisions

These are closed against the measured A/B/C/E runs. Do not reopen
classify optimisation until a new experiment beats C@8 on both quality
and latency. Later navigation work must not silently change them.

**Decision 1 — classify.** One semantic judgment = one candidate = one
Jev prompt. Other candidates must not share that prompt. Prompt-batching
collapsed precision from 95 % to 63 % (Experiment E). Isolated transport
batching is untested and is not a reason to change this contract.

**Decision 2 — execution.** Eight concurrent classify calls is the
measured starting cap. It is configurable; 16 queued and was slower.
This cap applies to classify, not to a future navigate operation.

1. **Hybrid search** is the auto-renewal retrieval baseline. It placed
   all 20 gold auto-renewal units in the top 50 on that question. It lost
   to dense on confidentiality. Do not introduce a Jev router until a
   simpler union or per-question choice has been measured.
2. A neighbor that contains the answer becomes a new candidate. It must
   not relabel the original TextUnit.
3. **Classify, navigate and coverage are three separate operations**,
   each with its own metrics. Jev must not become one function that
   classifies, picks graph edges and decides that the analysis is done.
4. **Completeness is still unsolved.** Retrieval rank cannot prove that
   nothing is missing.
5. A stable confidence cutoff is not a calibrated probability. Do not
   treat 0.9 as verified.

## Official classify baseline

Phase 2 classify performance is closed against Experiment C@8: same frozen
hybrid top-50, one TextUnit per call, concurrency 8, no extra context.

| Mätvärde | Baseline |
|---|---:|
| Precision / recall | 95 % / 95 % |
| Väggklocka | 1,831 s |
| Speedup mot sekventiellt | 7,66× |
| HTTP-anrop | 50 |
| Fel | 0 |
| Avtal 2 / 18 | oförändrade mot A |
| Etikettändringar mot C@1 | 0 |

The frozen snapshot lives at `baselines/phase2-jev-classify-c8.json`.
Do not overwrite `baselines/phase1-sequential-100-docx.json`. Labels were
stable across C@1/4/8/16; confidence scores were not. A fixed score cutoff
is not a calibrated probability.

## Phase 2b: Jev classification

Jev classifies the **frozen hybrid top-50**. It does not retrieve and does not
rerank. `UNCERTAIN` is a first-class label and is never dropped.

| Experiment | What Jev sees | Calls |
|---|---|---|
| A | TextUnit only, one candidate per call | 50 |
| B1 | TextUnit plus parent clause. Judge the candidate, not the parent. | 50 |
| B2 | TextUnit plus previous/next TextUnits. Judge the candidate, not the neighbors. | 50 |
| B | B1 then B2, compared against an A baseline | 100 |
| C | Same classify operation as A; concurrency 1 / 4 / 8 / 16 | 50 each |
| E | Same classify operation as C@8; batch size 1 / 4 / 8 / 16 at concurrency 8 | 50 / 13 / 7 / 4 |

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --retrieve-gold ./retrieval_gold/auto-renewal.json \
  --candidates ./data/retrieval-auto-renewal.json \
  --classify-jev \
  --jev-experiment A \
  --jev-model "$JEV_MODEL" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --output ./data/jev-hybrid-top50-A.json
```

Experiment B keeps the same frozen hybrid top-50 and the same question. It
compares each decision to Experiment A:

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --retrieve-gold ./retrieval_gold/auto-renewal.json \
  --candidates ./data/retrieval-auto-renewal.json \
  --classify-jev \
  --jev-experiment B \
  --jev-baseline ./data/jev-hybrid-top50-A.json \
  --jev-model "$JEV_MODEL" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --output ./data/jev-hybrid-top50-B.json
```

Experiment C freezes the A classify operation and only changes
concurrency. Each decision is compared to A and to the sequential C@1 run:

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --retrieve-gold ./retrieval_gold/auto-renewal.json \
  --candidates ./data/retrieval-auto-renewal.json \
  --classify-jev \
  --jev-experiment C \
  --jev-baseline ./data/jev-hybrid-top50-A.json \
  --jev-model "$JEV_MODEL" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --output ./data/jev-hybrid-top50-C.json
```

Experiment E is closed as a negative result: prompt-batching is faster
and destroys independence. Keep it as evidence, not as a classify path.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --retrieve-gold ./retrieval_gold/auto-renewal.json \
  --candidates ./data/retrieval-auto-renewal.json \
  --classify-jev \
  --jev-experiment E \
  --jev-baseline ./baselines/phase2-jev-classify-c8.json \
  --jev-timeout-seconds 30 \
  --jev-model "$JEV_MODEL" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --output ./data/jev-hybrid-top50-E.json
```

## Candidate union (no extra Jev calls)

Retrieval now reports `union_rrf` (dense + hybrid fused, cut at the same
`k`) and `union_pool` (all unique hits from both lists at that `k`).
`union_pool` can raise recall by classifying more text. `union_rrf` asks
whether the merge still helps when the classify budget stays at 50.

Measured on the corrected golds, R@50:

| Fråga | Dense | Hybrid | Union RRF (budget 50) | Union pool (storlek) |
|---|---:|---:|---:|---|
| Automatisk förlängning | 80 % | **100 %** | 90 % | 100 % (76) |
| Uppsägningstid | 69 % | **85 %** | 77 % | 85 % (68) |
| Ansvarsbegränsning | 65 % | **85 %** | 71 % | 88 % (69) |
| Sekretessplikt | **69 %** | 46 % | 54 % | 69 % (74) |
| Sekretessundantag | 86 % | **100 %** | 100 % | 100 % (63) |

At a fixed budget of 50, the better single strategy wins. The unbounded
pool only helps when we accept more classify calls. Do not add a Jev
router yet.

## Navigation probes (Avtal 46 and 49)

`--navigate` walks stored OverGraph relations only. It does not change
classify and does not run a general traverser.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --navigate \
  --output ./data/navigate-avtal-46-49.json
```

| Fall | Hopp | Extra enheter | Felaktiga hopp | Resultat |
|---|---|---:|---:|---|
| Avtal 46 | `PREVIOUS` from 12.4 | 2 | 1 (`NEXT` into 13 Sekretess) | Cap 12.3 found |
| Avtal 49 | `punkt 4` → clause heading | 6 | 0 | Title is informationssäkerhet, not sekretess |

Avtal 49 still needs a later evidence-assembly step. Isolated classify
on 6.3 should stay `UNCERTAIN`. The hop supplies the missing referent;
it does not relabel 6.3.

## Document Coverage v1

A deterministic controller on top of the existing scorer. No new Jev
prompt, no router, no general traverser. Classify is unchanged.
`VERIFIED_ABSENT` is emitted only when every TextUnit in that document
was examined. A top-k miss is `UNEXAMINED` or `NOT_FOUND`.

| Strategi | Vad den väljer |
|---|---|
| A `global_top_k` | Samma 50 globala kandidater som tidigare |
| B `document_scoped_n` | Topp *n* TextUnits i varje avtal |
| C `progressive_unexamined_n` | A, sedan topp *n* i dokument som inte fanns i A |

C is gold-blind: it cannot deepen a document that already appeared with
the wrong passage. Those leftovers are `touched_relevant_without_evidence`.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --coverage \
  --output ./data/coverage-v1.json
```

A/B/C share an in-process RRF hybrid (same fusion as the engine).
Measured hybrid:

| Fråga | A docR | C@3 anrop / extra | C docR | Orakel 100 % | Kvar |
|---|---:|---|---:|---|---|
| Automatisk förlängning | **100 %** vid 34 | 233 / +183 | 100 % | **34** | 0 |
| Uppsägningstid | 85 % | 239 / +189 | **100 %** | **129** | 0 |
| Ansvarsbegränsning | 89 % | 239 / +189 | 96 % | aldrig med C | Avtal 67 touched |
| Sekretessplikt | 46 % | 233 / +183 | 62 % | inte med C | 5 touched |
| Sekretessundantag | **100 %** vid 13 | 233 / +183 | 100 % | **13** | Avtal 46 `NEEDS_ANALYSIS` |

C is gold-blind, so it still fetches unexamined documents after A is
already complete. The oracle column is when the last positive actually
appeared. Dense `document_scoped_3` is what recovers confidentiality:
100 % at 209 units. Hybrid `document_scoped_5` also reaches 100 %, but
only at 313. Avtal 46 still needs the measured `PREVIOUS` hop.

No relevant document was marked `VERIFIED_ABSENT`.

## Document Coverage v2

Deterministic controller on the same five questions, same hybrid ranking,
and same gold. Jev C@8 is unchanged: one TextUnit per prompt, concurrency 8,
C@8 judgments reused so a unit is never asked twice for the same question.

Two variants after global top-50:

| Variant | Vilka dokument fördjupas |
|---|---|
| `touched` | Bara dokument som redan har klassificerade träffar men saknar avgörande evidens |
| `fair` | Samma, plus ett nytt dokument per pass bland de som fortfarande är `UNEXAMINED` |

A retrieved unit is not a classified unit. `NO_EVIDENCE_YET` never becomes
`VERIFIED_ABSENT`. That status is emitted only when every TextUnit in the
document has been classified. Existence questions stop a document after the
first `YES`. Multi-clause questions stay in `NEEDS_ANALYSIS` until a measured
hop (`PREVIOUS` / `SAME_SECTION` / `punkt N`) has been attempted.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --jev-concurrency 8 \
  --coverage-v2 \
  --coverage-v2-passes 3 \
  --output ./data/coverage-v2.json
```

Measured (`jev-1.13.0`, C@8 cache, 95.2 s wall for all five golds × both
variants). `document_recall` is documents in `EVIDENCE_FOUND`. The Jev-yes
column is documents where Jev already said `YES` — that is the stop-signal
curve. v1 measured gold-span overlap, not Jev.

| Fråga | v1 A gold | touched Jev-yes / anrop | fair Jev-yes / anrop | Alla relevanta vid | Olösta relevanta | Olösta totalt |
|---|---:|---:|---:|---|---|---:|
| Automatisk förlängning | 100 % @ 34 | 95 % / 65 | 95 % / 172 | aldrig (Jev) | Avtal 18, 22 | 81 / 77 |
| Uppsägningstid | 85 % | 85 % / 56 | **100 %** / 180 | fair pass 2 (213 klassificerade) | touched: Avtal 17, 79 `UNEXAMINED` | 75 / 69 |
| Ansvarsbegränsning | 89 % | 93 % / 26 | **100 %** / 177 | fair pass 1 (122 klassificerade) | touched: Avtal 41, 51 `UNEXAMINED` | 69 / 62 |
| Sekretessplikt | 46 % | 85 % / 59 | **100 %** / 159 | fair pass 3 (266 klassificerade) | touched: Avtal 13, 22, 34, 36 | 77 / 65 |
| Sekretessundantag | 100 % @ 13 | **100 %** / 104 | **100 %** / 183 | touched pass 1 (89 klassificerade, 10 hopp) | 0 | 93 / 92 |

Inga relevanta dokument blev `VERIFIED_ABSENT`. Fair öppnar `UNEXAMINED` och
betalar för det: 159–183 nya Jev-anrop per fråga mot 26–104 för touched.

The cheap strategy still depends on the question. Touched recovers Avtal 67
on liability (the v1 C leftover) in one pass, then stops. It cannot recover
notice-period Avtal 17/79 because those documents were never in the top-50.
Fair finds them on pass 2. Confidentiality is the expensive existence
question: fair needs three passes to reach Jev-yes 100 %. Carve-out is
already complete in global top-50; the extra cost is hops plus deepening
documents that are still `NO_EVIDENCE_YET`.

Avtal 18 on auto-renewal is the known C@8 false negative (`Annars förlängs
avtalet tills vidare` vs the classified 4.2-passage). Avtal 22 stayed
`UNCERTAIN` on a heading. Deepening inside those documents did not produce a
`YES`. That is classify disagreement with gold, not an unexamined miss.

v1 C always paid ~180 extra units after A was already complete. v2 touched
stops a document after existence-`YES`, so auto-renewal costs 65 live Jev
calls instead of classifying 233 candidates. The remaining cost is
unresolved documents: 61–63 stay `UNEXAMINED` under touched, and 57–92 stay
`NO_EVIDENCE_YET` under fair. Those must not be reported as verified
negative.

## Document Coverage v3

Same hybrid ranking, same five questions, same Jev C@8 contract. The
controller adds a per-document classify budget and a proof-kind stop.

| Proof kind | When the document is done |
|---|---|
| `EXISTS` | First `YES` |
| `COMPOSITE` | Every required evidence part is present in classified text |
| `ABSENCE` | Every TextUnit classified and no `YES` |

`BUDGET_EXHAUSTED` means the examination stopped unfinished. It is not
`VERIFIED_ABSENT`. Cached C@8 answers count toward the budget and are
never asked again. Heading `UNCERTAIN` navigates to children; a `punkt N`
reference follows that clause. `NEXT` is still not used.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --jev-concurrency 8 \
  --coverage-v3 \
  --coverage-budgets 1,2,3,5 \
  --output ./data/coverage-v3.json
```

Measured (`jev-1.13.0`, 133 s wall). v3 always opens every document
(fair). `classified` is units examined. Live Jev calls are incremental
across B1→B5 because later budgets reuse earlier answers.

| Fråga | v2 bästa | Första v3-match | Klassificerade | Nya Jev till match | Olösta relevanta |
|---|---|---|---:|---:|---|
| Automatisk förlängning | 95 % / 65 touched | **B1** 95 % | 100 | **60** | Avtal 18 `BUDGET_EXHAUSTED` |
| Uppsägningstid | 100 % / 180 fair | **B2** 100 % | 193 | **146** | 0 |
| Ansvarsbegränsning | 100 % / 177 fair | **B2** 100 % | 177 | **131** | 0 |
| Sekretessplikt | 100 % / 159 fair | **B5** 100 % | 354 | **306** | 0 |
| Sekretessundantag Jev-yes | 100 % / 104 touched | **B1** 100 % Jev-yes | 100 | **62** | 7 `NEEDS_ANALYSIS` |
| Sekretessundantag evidens | (v2 mätte inte delarna) | **B3** 100 % `EVIDENCE_FOUND` | 298 | **249** | 0; Avtal 46 båda delarna |

No relevant document was `VERIFIED_ABSENT`. After the first match the
remaining documents sit in `BUDGET_EXHAUSTED` (56–92), not in a negative
conclusion.

Recall per extra examined unit:

| Fråga | B1 | B2 | B3 | B5 |
|---|---:|---:|---:|---:|
| Automatisk förlängning | **95 %** | 95 % | 95 % | 95 % |
| Uppsägningstid | 77 % | **100 %** | 100 % | 100 % |
| Ansvarsbegränsning | 89 % | **100 %** | 100 % | 100 % |
| Sekretessplikt | 77 % | 77 % | 92 % | **100 %** |
| Sekretessundantag Jev-yes | **100 %** | 100 % | 100 % | 100 % |
| Sekretessundantag `EVIDENCE_FOUND` | 0 % | 29 % | **100 %** | 100 % |

B5 does not move auto-renewal. Avtal 18 is the known template/alternative
misclassification; more units are the wrong action. Avtal 22 on
auto-renewal is found at B1. On confidentiality it stays unresolved
through B2 and is recovered at B3 by a heading→child hop, not by spraying
budget.

COMPOSITE is the other split: B1 already has Jev-yes on all seven
carve-out documents, but Avtal 46 has only the carve-out passage. The
cap arrives at B3 (`found 2/2`). Until then those documents stay
`NEEDS_ANALYSIS`. That is evidence gathering, not a search for more
positive documents.

B∞ was not run. Opening every remaining TextUnit would classify
thousands of units and would not fix Avtal 18.

## Query expansion v1

Coverage v3 stays the coverage reference. This experiment goes back to
retrieval: the same five questions, same dense/sparse/hybrid scorers, no
LLM, no Jev, no C@8 change. Each gold has a concept in
`retrieval_gold/expansions.json`. Terms are legal variants, not gold
passage snippets.

| Variant | Query |
|---|---|
| `baseline` | Original gold query |
| `append` | Query plus unused concept terms |
| `fuse` | RRF of baseline and append rankings |

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --expand-queries \
  --output ./data/query-expansion-v1.json
```

Measured hybrid (`text-embedding-3-large`, 28.5 s wall). Document
coverage at 50 and units to 100 % document-recall are gold-span, not Jev.

| Fråga | Baseline R@50 / orakel | Append | Fuse |
|---|---|---|---|
| Automatisk förlängning | 100 % / 34 | 100 % / **28** | 100 % / **26** |
| Uppsägningstid | **85 %** / 157 | 69 % / **73** | **85 %** / **91** |
| Ansvarsbegränsning | 82 % pass, 89 % dok / 85 | 76 % pass, **93 %** dok / 85 | 85 % pass, **93 %** dok / **74** |
| Sekretessplikt | 46 % / 181 | **85 %** / **55** | 77 % / 96 |
| Sekretessundantag | 100 % / 13 | 100 % / 16 | 100 % / **12** |

Confidentiality is the intended win: hybrid R@50 goes from 46 % to 85 %,
and 100 % document-recall moves from 181 units to 55. Sparse alone jumps
from 8 % to 85 %. That is the cheap lexical gap `sekretessplikt` vs
`sekretess` / `tystnadsplikt` / `konfidentiell information` /
`företagshemligheter`.

Append is not free. Notice-period hybrid R@50 falls from 85 % to 69 %
because extra terms pull in the wrong passages, even though the tail
shortens (157 → 73). Fuse keeps the baseline top-50 and still cuts the
oracle. Carve-out was already complete; append adds one hard negative
and slows the oracle slightly.

This is not a new default retriever. Query expansion v1 is frozen
experimental data. Classify stays C@8.

Held-out generalization golds stay out of default coverage/classify:

| Fråga | Query | Lexikon | Facit |
|---|---|---|---|
| `governing-law` | lagvalsklausul | tillämplig lag / rätt, lagval | 75 dokument med operativt lagval |
| `force-majeure` | befrielsegrund vid oförutsedda händelser | force majeure, vis major, hinder utanför kontroll | 5 operativa avtal |

The held-out terms were written from the legal concept, not from gold
snippets. Do not add `svensk lag` just because the corpus says that.
Avtal 06 leftover on confidentiality is the same rule: do not grow the
lexicon to lift one leftover document.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --expand-queries \
  --output ./data/query-expansion-v2.json
```

Each gold now reports isolated retrieval latency: query embedding,
dense search, sparse search, and hybrid fusion. End-to-end wall time
still includes real cache hits. Unique classifications and cumulative
Jev calls stay the cost that is independent of cache.

Measured hybrid (`text-embedding-3-large`, 23.6 s wall, isolated
ranking ~1.2 s per query after encode):

| Fråga | Split | Baseline R@50 / orakel | Append | Fuse |
|---|---|---|---|---|
| Automatisk förlängning | seen | 100 % / 34 | 100 % / **28** | 100 % / **26** |
| Uppsägningstid | seen | **85 %** / 157 | 69 % / **73** | **85 %** / **91** |
| Sekretessplikt | seen | 46 % / 181 | **85 %** / **55** | 77 % / 96 |
| Lagvalsklausul | held-out | 16 % / 542 | **55 %** / **137** | 40 % / 252 |
| Befrielsegrund | held-out | 100 % / 33 | 100 % / **5** | 100 % / 13 |

Governing-law has 75 relevant documents, so Recall@50 cannot exceed
67 %. Append finds 41 of them (55 %); baseline finds 12 (16 %). The
lexicon does not contain `svensk lag`. Sparse still only reaches 9 %,
while dense was already 51 %. Hybrid without expansion is worse than
dense here because empty sparse ranks dilute RRF.

Force-majeure was already complete at k=50 via dense. Append still
matters: sparse goes from 0 % to 100 %, Recall@5 from 0 % to 100 %,
and the oracle from 33 units to 5. One hard negative (Avtal 31 vite)
enters the top-50.

Isolated retrieval, warm encode:

| Steg | Tid |
|---|---:|
| Query embedding | ~0,2 s |
| Dense search | ~0,60 s |
| Sparse search | ~0,59 s |
| Hybrid fusion | ~3 ms |
| Ranking totalt | ~1,2 s |

Those dense/sparse numbers were **Python exhaustive ranking**, not
OverGraph `vector_search`. Dense and sparse ran sequentially. See
retrieval latency v1.

The 10,2 s to full confidentiality evidence is therefore mostly Jev,
not retrieval. Notice-period still regresses under append, so the
default retriever stays the original query.

## Retrieval latency v1

The 600 ms "dense search" and 590 ms "sparse search" were not the
database. Expansion v2 timed `exhaustive_rank` over every TextUnit in
Python and always passed both query vectors, so the sparse path still
paid for unused cosine.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --retrieve-gold ./retrieval_gold/confidentiality.json \
  --profile-retrieval \
  --repeats 5 \
  --candidate-k 50 \
  --output ./data/retrieval-latency-v1.json
```

Measured on 2 548 TextUnits, 3 072-d dense, mean 32 sparse values,
five repeats after warmup:

| Steg | Tid |
|---|---:|
| Ladda publicerade enheter (engång) | 367 ms |
| Query embedding, kall | 549 ms |
| Query embedding, varm | **217 ms** |
| Python cosine över alla enheter | **562 ms** |
| Python sparse-dot över alla enheter | **5 ms** |
| Python dense rank (score + sort) | 625 ms |
| Python sparse rank (fortfarande cosine + sparse) | 583 ms |
| Python dense sedan sparse | **1 212 ms** |
| OverGraph `vector_search` dense k=50 | **12 ms** |
| OverGraph `vector_search` sparse k=50 | **0,07 ms** |
| OverGraph `vector_search` hybrid k=50 | **12 ms** |
| Hydrering ovanpå hybrid | +0,7 ms |

OverGraph search is about 12 ms. The earlier 1,2 s was the quality
oracle: a pure-Python loop of 7,8 million dense multiply-adds, run
twice because dense and sparse are sequential.

Frozen as `baselines/phase2-overgraph-hybrid-search.json`. Normal
retrieval is about 230 ms (217 ms encode + 12 ms hybrid). Do not
optimize the engine from this number. It does not replace C@8
(1,83 s for 50 parallel Jev judgments).

## Expansion decision v1

Representation is a separate stage: question → representation →
retrieval → classify → coverage. The default retriever stays
unexpanded. The first decision rule is a priori, not fitted: expand
when Jaccard of dense vs sparse top-20 is below 0,25.

Reserved golds were not used to design the first lexicon:

| Fråga | Never R@50 | Always | Regel |
|---|---:|---:|---|
| Personuppgifter | 53 % (8/15) | **67 %** (10/15) | same as always |
| Partsbyte | 88 % (7/8) | 88 % (7/8) | same as always |

The rule expanded on every gold, including notice-period where append
drops Recall@50 from 85 % to 69 %. Frozen as rejected in
`baselines/phase2-jaccard-expansion-routing-rejected.json`, the same
way prompt batching was rejected for classify. Do not tune the
Jaccard threshold on these golds. Query expansion stays optional. The
router is still unsolved.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --decide-expansion \
  --output ./data/expansion-decision-v1.json
```

## Coverage v3 + append on confidentiality

Same controller, same Jev C@8, same budgets, same stop rules. Only the
hybrid ranking for `confidentiality` changes. The default retriever is
unchanged. Baseline numbers are the frozen Coverage v3 run.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --coverage-v3 \
  --coverage-gold-id confidentiality \
  --coverage-query-variant append \
  --coverage-v3-baseline ./data/coverage-v3.json \
  --output ./data/coverage-v3-append-confidentiality.json
```

Measured (`jev-1.13.0`, 23.2 s wall for the append run):

| Mått | Baseline v3 | Append + v3 |
|---|---:|---:|
| Retrieval Recall@50 | 46 % | **85 %** |
| Första 100 % dokument-recall | B5 | **B2** |
| Klassificerade då | 354 | **165** |
| Nya Jev-anrop till 100 % | 306 | **131** |
| `BUDGET_EXHAUSTED` vid 100 % | 56 | 56 |
| Falska negativa | 0 | 0 |
| Väggklocka till 100 % | 21,5 s | **10,2 s** |

B1 already finds 12 of 13 relevant contracts (92 %) with the same 100
classifications that baseline used for 77 %. The leftover is Avtal 06,
recovered on the second unit. Append B1 asks 72 live Jev calls against
baseline's 61 because C@8 cached the original top-50; better candidates
are cache misses.

Recall@50 +39 points did not cut Jev cost by 39 %. It cut the path to
full evidence roughly in half (−53 % classified, −57 % new Jev calls)
because the controller still opens every document and still stops on
`EXISTS` + `YES`. `BUDGET_EXHAUSTED` remains unresolved, not absent.

This run is frozen as
`baselines/phase2-coverage-v3-append-confidentiality.json`. It does not
replace official C@8 or Coverage v3. Append stays optional. Completeness
is still unsolved: 56 documents remain `BUDGET_EXHAUSTED` after all
positives are found.

## Embedding models v1

Same retriever, same seen golds, candidate budget 50. Only the embedding
pair changes. The official 3072 database is read-only. C@8 and Coverage
v3 stay frozen.

| Variant | Dense | Sparse | Database |
|---|---|---|---|
| `openai-tfidf` | text-embedding-3-large 3072 | lexical-tfidf-hash-v1 | official phase-2, no writes |
| `bge-m3-tfidf` | BGE-M3 1024 | lexical-tfidf-hash-v1 | new 1024-d graph |
| `bge-m3` | BGE-M3 1024 | BGE-M3 sparse | new 1024-d graph |
| `openai-bge-sparse` | text-embedding-3-large 3072 | BGE-M3 sparse | copy of official, sparse rewritten |

```bash
uv sync --extra local
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --input ./data/extra_corpus \
  --cache-dir ./data/extra-cache \
  --collection extra-corpus \
  --openai-api-key "$OPENAI_API_KEY" \
  --compare-embeddings \
  --repeats 3 \
  --output ./data/embedding-models-v1.json
```

Reports Recall@20/@50, document-recall, hard-negative ranks, corpus
embed time, cold and warm query encode, engine search, and peak RSS.
Do not assume BGE-M3 wins.

Measured (engine hybrid, k=50, seen golds, official 3072 DB unread-only):

| Variant | Auto R@50 | Notice | Liability | Sekretess | Carve-out | Varm query |
|---|---:|---:|---:|---:|---:|---:|
| OpenAI + TF-IDF | **95 %** | 77 % | **85 %** | 54 % | 100 % | 260 ms |
| BGE-M3 + TF-IDF | 90 % | **85 %** | **85 %** | 54 % | 100 % | 143 ms |
| BGE-M3 + BGE-M3 | 95 % | **85 %** | 62 % | **62 %** | 100 % | **107 ms** |
| OpenAI + BGE-M3 | **95 %** | 77 % | 62 % | **62 %** | 100 % | 330 ms |

BGE-M3 sparse lifts confidentiality (8 % → 62 % sparse R@50) and
drops liability-cap hybrid from 85 % to 62 %. BGE-M3 + TF-IDF puts
the Avtal 15 hard negative at rank 1 on auto-renewal. Load was 177 s;
peak RSS 4,9 GB; corpus embed 75–153 s.

Frozen as rejected in `baselines/phase2-bge-m3-rejected.json`. Default
retriever stays OpenAI 3072 + TF-IDF. No GPU server. Do not compare
these engine Recall@50 numbers to the earlier exhaustive expansion
run as if they were the same measurement.

## Analysis cost v1

Same C@8 rankings and the same classifier. The question is how much
Jev work a ranking forces before the first gold-relevant `YES`.
`BUDGET_EXHAUSTED` is still not absent.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --analysis-cost \
  --output ./data/analysis-cost-v1.json
```

Measured on frozen C@8 lists (no new Jev calls):

| Fråga | Första relevant | Första verifierade YES | Falska YES före | Jev till första evidens |
|---|---:|---:|---:|---:|
| Automatisk förlängning | 1 | 1 | 0 | 1 |
| Uppsägningstid | 2 | 2 | 1 | 2 |
| Ansvarsbegränsning | 4 | 4 | 3 | 4 |
| Sekretess | 1 | 1 | 0 | 1 |
| Sekretessundantag | 2 | 2 | 1 | 2 |

Frozen as `baselines/phase2-first-verified-evidence.json`. Do not optimize
ranking to move first YES from rank 2 to rank 1. First evidence answered
its question: a document-existence answer is already cheap. A workspace
inventory is a different evidence-coverage contract, not a second retriever.

`BUDGET_EXHAUSTED` still means unresolved, never absent.

## Evidence curve v1

Same frozen C@8 lists and Coverage v3 B5 timeline. No new Jev calls.
X is cumulative classifications. Y is unique documents with verified
positive evidence. Ranking checkpoints use C@8 order. Workspace
checkpoints hold the last Coverage v3 phase at or before that count.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --evidence-curve \
  --output ./data/evidence-curve-v1.json
```

Ranking curve (C@8 order, gold passage + Jev `YES`, unique documents):

| Fråga | @10 | @25 | @50 |
|---|---:|---:|---:|
| Automatisk förlängning | 8 | 18 | 19 |
| Uppsägningstid | 6 | 10 | 11 |
| Ansvarsbegränsning | 5 | 9 | 11 |
| Sekretess | 1 | 3 | 6 |
| Sekretessundantag | 4 | 5 | 5 |

Workspace curve (Coverage v3 B5, gold document + Jev `YES`). Checkpoints
hold the last phase at or before that count. Phase snapshots start at 50.

| Fråga | @50 | @100 | @150 | @200 | Sista nya positiva | Klassificeringar därefter | Facit |
|---|---:|---:|---:|---:|---:|---:|---:|
| Automatisk förlängning | 19 | 19 | 19 | 19 | 50 | 363 | 19/20 |
| Uppsägningstid | 11 | 11 | 11 | 11 | 213 | 195 | 13/13 |
| Ansvarsbegränsning | 25 | 25 | 28 | 28 | 122 | 245 | 28/28 |
| Sekretess | 8 | 8 | 10 | 13 | 196 | 158 | 13/13 |
| Sekretessundantag | 7 | 7 | 7 | 7 | 50 | 432 | 7/7 |

Two cost regimes. The first 50 classifications find most of the positives
the ranking can verify. After the last new positive, Coverage v3 still
spends 158–432 classifications and leaves 56–92 documents
`BUDGET_EXHAUSTED`. Gold-complete is not system-complete.

The ranking and workspace curves are not the same count: C@8 verifies
gold snippets, Coverage v3 counts gold documents that received any Jev
`YES`. Liability-cap is the gap (11 versus 25 at 50).

Frozen as `baselines/phase2-evidence-curve-v1.json`. Does not replace
official C@8 or Coverage v3.

## Workspace stop replay v1

Coverage v3 is unchanged. This is a replay of the observed B5 path at
workspace stop budgets 50 / 100 / 150 / 200 / 300. No new Jev calls and
no new stop rule. Checkpoints hold the last phase at or before the
budget. `PARTIAL` means the investigation ended with unresolved
documents. It does not mean every positive document has been found.
`BUDGET_EXHAUSTED` is still not absent.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --workspace-stop-replay \
  --output ./data/workspace-stop-replay-v1.json
```

Jev `YES` documents / complete evidence / unresolved / saved
classifications:

| Fråga | @50 | @100 | @150 | @200 | @300 |
|---|---|---|---|---|---|
| Automatisk förlängning | 19 / 19 / 80 / 363 | 19 / 19 / 80 / 363 | 19 / 19 / 77 / 283 | 19 / 19 / 77 / 283 | 19 / 19 / 76 / 130 |
| Uppsägningstid | 11 / 11 / 84 / 358 | 11 / 11 / 84 / 358 | 11 / 11 / 79 / 274 | 11 / 11 / 79 / 274 | 13 / 13 / 69 / 123 |
| Ansvarsbegränsning | 25 / 25 / 72 / 317 | 25 / 25 / 72 / 317 | 28 / 28 / 66 / 245 | 28 / 28 / 63 / 179 | 28 / 28 / 62 / 116 |
| Sekretess | 8 / 8 / 78 / 304 | 8 / 8 / 78 / 304 | 10 / 10 / 68 / 226 | 13 / 13 / 58 / 158 | 13 / 13 / 58 / 100 |
| Sekretessundantag | 7 / **0** / 100 / 432 | 7 / **0** / 100 / 432 | 7 / 7 / 93 / 332 | 7 / 7 / 93 / 332 | 7 / 7 / 93 / 239 |

Every measured stop, including the full B5 run, is `PARTIAL`. No run
reaches `COMPLETE`. Avtal 18 stays unresolved on auto-renewal after 413
classifications.

Stopping at 50 saves 304–432 classifications. It also drops later
positives: two notice-period contracts (found at 213), three
liability-cap contracts (found at 122), and five confidentiality
contracts (found by 196). Sekretessundantag already has seven Jev `YES`
at 50, but complete `COMPOSITE` evidence arrives only at 150.

Cost of the next gain after stop 50:

| Fråga | Nästa Jev YES | Nästa komplett evidens |
|---|---|---|
| Automatisk förlängning | ingen | ingen |
| Uppsägningstid | 163 klassificeringar / 2 dokument | samma |
| Ansvarsbegränsning | 72 / 3 | samma |
| Sekretess | 78 / 2 | samma |
| Sekretessundantag | ingen mer YES | 100 / 7 |

Unresolved kinds at a stop are a hypothesis from status counts, not a
new controller: insufficiently examined, unclear or conflicting, and
composite-incomplete. Avtal 18 belongs with classification difficulty,
not with more generic retrieval.

Frozen as `baselines/phase2-workspace-stop-replay-v1.json`. Does not
replace official C@8 or Coverage v3. Do not pick a stop rule from this
replay alone.

Frozen conclusions from the replay:

- A fast `PARTIAL` answer is possible, but its coverage must be disclosed
  as incomplete.
- Jev `YES` is not legal evidence. `COMPOSITE` needs proof completion.
- No general stop budget follows from these curves. Continued work
  sometimes finds new positives and sometimes the missing proof.
- The open problem is work allocation, not engine speed.

Those are two different jobs on the same OverGraph: **discovery** of
unseen documents, and **proof completion** of evidence already in hand.

## Proof gap v1

Coverage v3 is unchanged. No new controller. The question is how far
first signal sits from complete proof, and whether a deterministic hop
can close that gap.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --proof-gap \
  --output ./data/proof-gap-v1.json
```

On the C@8 lists, only sekretessundantag has a true complementary-passage
gap: Avtal 46 has the carve-out at rank 2 and is missing the liability
cap. A measured `PREVIOUS` hop fetches that cap in two extra TextUnits,
navigation recall 1.0, no new Jev in the hop measurement. Avtal 49 has
an open `punkt 4` reference (UNCERTAIN); the hop reaches information
security, not secrecy.

The other six carve-out contracts already contain the legal exception in
the first YES sentence. Coverage v3 still waits for a hop before it
marks them complete. That is controller completeness, not missing legal
text.

Workspace distance on Coverage v3 B5:

| Fråga | Alla Jev YES | Komplett evidens | Klassificeringar emellan | Jobb |
|---|---:|---:|---:|---|
| Automatisk förlängning | aldrig 20/20 | aldrig | — | discovery / Avtal 18 |
| Uppsägningstid | 213 | 213 | 0 | discovery |
| Ansvarsbegränsning | 122 | 122 | 0 | discovery |
| Sekretess | 196 | 196 | 0 | discovery |
| Sekretessundantag | 50 | 150 | **100** | proof completion |

The hop that finishes Avtal 46 is cheap. The 100 classifications between
workspace YES and complete evidence are mostly in-document coverage, not
the missing `PREVIOUS` unit. Prioritizing the known gap is still a
hypothesis: this replay cannot show what an adaptive order would have
found.

Frozen as `baselines/phase2-proof-gap-v1.json`. Does not replace official
C@8 or Coverage v3.

## Proof contract v1

Coverage v3 is unchanged. This compares two `COMPOSITE` rules on the
frozen carve-out C@8 texts. No new Jev calls and no new controller.
Jev `YES` is not enough: each part of
`ansvarsbegränsning → undantag → sekretessbrott` must be visible in the
text. A hop is required only when a part is missing, a coverage sibling
is missing, or a `punkt N` reference does not name secrecy.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --proof-contract \
  --output ./data/proof-contract-v1.json
```

| Regel | Kompletta vid första signal | Kräver komplettering | Oavgjord hänvisning |
|---|---:|---|---|
| A. Hopp alltid | 0 / 7 | alla sju | — |
| B. Relation i text | **6 / 7** | Avtal 46 | Avtal 47, Avtal 49 |

The six complete documents show the cap, the exception, and secrecy in
the same TextUnit. Avtal 46 still needs the sibling cap sentence. Avtal
49's `punkt 4` hop remains unresolved: the reference is not secrecy.
Hard negatives Avtal 37 and 50 stay incomplete because secrecy is
missing. None of the controls become complete.

This does not claim that 100 Coverage v3 classifications would be saved.
That number is the observed B5 path. A different proof rule would change
later candidate choice.

Discovery stays a separate problem. Proof completion should require
complete legal evidence, not a mandatory hop.

Frozen as `baselines/phase2-proof-contract-v1.json`. Not applied to
Coverage v3.

Evidence work splits in three layers, separate from Coverage v3:

| Layer | Job |
|---|---|
| Retrieval | Find candidate evidence |
| Proof evaluation | Decide whether the text supports the legal relation |
| Navigation | Complete or test evidence when a part is missing or a reference is unclear |

`COMPOSITE` describes the proof, not the number of TextUnits. Navigation
is not a required hop count.

## Proof work v1

Same frozen C@8 list and the measured Avtal 46 / Avtal 49 hops. Coverage
v3 is unchanged. This is a replay, not a new coverage run, and it does
not claim that 100 classifications disappear.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --proof-work \
  --output ./data/proof-work-v1.json
```

| Mått | Regel B replay | Observerad v3 B5 |
|---|---:|---:|
| Kompletta från första kandidat | 6 / 7 | 0 / 7 |
| Nödvändiga grafhopp | 1 (`PREVIOUS`, Avtal 46) | hopp alltid |
| Oavgjorda hänvisningar | 2 (Avtal 47, 49) | — |
| Falskt kompletta kontroller | 0 | — |
| Klassificeringar till sju kompletta | **14** | **150** |
| Senare coverage-körning med samma budget | inte körd | 482 totalt |

The 14 are C@8 ranks through the last gold signal (13) plus one classify
of the Avtal 46 cap. Avtal 49 still needs a dismissive `CLAUSE_4` hop;
that is reference testing, not gold completion.

A later Coverage run with Rule B and the same budget is still required
before the contract enters the controller. That run is now frozen below.
Replay 14 is not its result.

Frozen as `baselines/phase2-proof-work-v1.json`. Does not replace
official C@8 or Coverage v3.

## Coverage v3 + Rule B

Same controller, retrieval ranking, C@8 contract, gold, discovery, and
`PARTIAL` / `BUDGET_EXHAUSTED` / `VERIFIED_ABSENT` semantics. The only
change is COMPOSITE proof: hop if the legal relation is missing or a
reference is unresolved. Default Coverage v3 stays hop-always.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --coverage-v3 \
  --coverage-gold-id liability-secrecy-carveout \
  --proof-rule relation \
  --coverage-v3-baseline ./data/coverage-v3.json \
  --output ./data/coverage-v3-relation-carveout.json
```

Measured live (`jev-1.13.0`, 35 s wall). Do not read replay 14 as the
expected total.

| Mått | Regel B live | Officiell v3 |
|---|---:|---:|
| Kompletta vid B1 | **6 / 7** | 0 / 7 |
| Kvar vid B1 och B2 | Avtal 46 | alla sju |
| Första sju kompletta | **143** (B3) | **150** (B3) |
| Arbete efter komplett (B3) | 147 | 148 |
| Klassificeringar B5 | 468 | 482 |
| Jev-anrop B5 | 178 | 184 |
| Grafhopp B5 | 6 | 12 |
| Falskt kompletta kontroller | **5** | inte mätt |

Avtal 46 still needs the complementary `PREVIOUS` hop. Avtal 49 stays
incomplete after `punkt 4` → informationssäkerhet. Those two regression
cases hold.

The 136 extra classifications in the replay were not the old hop-always
rule. Live Rule B saves 7 classifications to first complete and 14 at
B5. The rest is fair discovery of other documents.

Rule B is not ready. Joining classified units treats a generic liability
exception plus a later `Sekretess` heading as a complete carve-out.
False completes: Avtal 37, 47, 50, 77, 78. Avtal 47 was an unresolved
reference on C@8; the second unit supplied the word *sekretess*.

Frozen as `baselines/phase2-coverage-v3-relation-carveout.json`. Does
not replace official C@8 or Coverage v3. Rule B is rejected.

## Proof link v1

Coverage v3 is unchanged. This is proof evaluation only: a relation
must be grounded in one passage or in an explicit, resolved reference.
Joining classified units and re-running the keyword detector is the
Rule B failure and is not used here.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --proof-link \
  --output ./data/proof-link-v1.json
```

| Fall | Resultat |
|---|---|
| Sju guldmeningar med `gäller inte/utom vid … sekretess` | **länkad relation** |
| Avtal 46: 12.3-cap + 12.4-undantag | länkad via 12.4, inte via sammanslagning |
| Avtal 37, 50, 77, 78: undantag + rubriken Sekretess | **inte belagd** |
| Avtal 47: `punkt 8` + `11. Sekretess` | **inte belagd** (fel klausul) |
| Avtal 49: `punkt 4` → informationssäkerhet | **inte belagd** |
| Två enheter med alla nyckelord, ingen koppling | `cooccurrence_only` |

The detector keeps the seven true positives and produces zero false
completes on the known controls. It does not enter Coverage v3.

A later isolated coverage run with this detector is the next cost.
Discovery work is a separate problem.

Frozen as `baselines/phase2-proof-link-v1.json`. Does not replace
official C@8 or Coverage v3.

## Coverage v3 + linked relation

Same controller, ranking, C@8, gold, and discovery. The only change is
proof evaluation: a COMPOSITE document is complete when a passage or a
resolved reference grounds the link. Default Coverage v3 stays
hop-always.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --coverage-v3 \
  --coverage-gold-id liability-secrecy-carveout \
  --proof-rule link \
  --coverage-v3-baseline ./data/coverage-v3.json \
  --output ./data/coverage-v3-link-carveout.json
```

Measured live (`jev-1.13.0`, 33 s wall).

| Mått | Länkdetektor | Officiell v3 |
|---|---:|---:|
| Sanna kompletta vid B1 | **7 / 7** | 0 / 7 |
| Första sju kompletta | **39** (B1) | **150** (B3) |
| Klassificeringar B5 | 477 | 482 |
| Jev-anrop B5 | 186 | 184 |
| Falskt kompletta | **0** | 1 extra `EVIDENCE_FOUND` |
| `BUDGET_EXHAUSTED` | 91, inget relevant | 92, inget relevant |

Avtal 46 completes from 12.4 alone. The gold coverage group still lists
12.3; that inventory is not the legal relation. Avtal 47 and 49 stay
open for navigation (`CLAUSE_4` / `PREVIOUS`) and do not become
complete.

The detector holds the quality bar inside the live controller. Total
B5 work does not drop. Discovery is unchanged.

Not applied to the default controller. Seven known positives and the
measured false-complete controls are not enough legal phrasing.

Frozen as `baselines/phase2-coverage-v3-link-carveout.json`. Does not
replace official C@8 or Coverage v3.

## Proof morph v1

Forty controlled clause variations against the unchanged link detector.
Not a blind corpus and not a substitute for new contracts. The detector
was not retuned on this material.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --proof-morph \
  --output ./data/proof-morph-v1.json
```

| Grupp | Godkända | Vad som brast |
|---|---:|---|
| Synonymer | 3 / 10 | *tystnadsplikt*, *konfidentiell*, *obegränsat*, *undantas* |
| Negationer | 8 / 10 | två falskt kompletta |
| Hänvisningar | 9 / 10 | `klausul 9` är inte `punkt N` |
| Samförekomst | 10 / 10 | A/B/C utan länk förblir obelagda |

`gäller även vid sekretessbrott` skiljs från `gäller inte vid sekretessbrott`.
That distinction is lexical: the trigger is the phrase `gäller inte`, not
a parse of opposition.

Two false completes stay on the record:

- `gäller inte vid grov vårdslöshet. Sekretess regleras separat.` matches
  across the period inside one unit.
- `gäller inte, utom vid sekretessbrott` inverts the carve-out; the
  detector still sees `gäller inte` plus `sekretess`.

Synonym recall is 0.30. The detector recognizes the seed phrasing, not
the legal relation under paraphrase.

Frozen as `baselines/phase2-proof-morph-v1.json`. Does not replace
official C@8 or Coverage v3.

## Proof Jev morph v1

Same 40 morph cases. Jev is a separate proof evaluator: one judgment
per prompt, `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT`. C@8 classify
is unchanged. Diagnostic, not a blind test.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --proof-jev \
  --output ./data/proof-jev-morph-v1.json
```

Measured live (`jev-1.13.0`, 45 judgments, 2.1 s wall, 352 ms mean).

| Mått | Jev proof | Deterministisk länk |
|---|---:|---:|
| Parafraser `SUPPORTED` | **10 / 10** | 3 / 10 |
| `gäller även` mot `gäller inte` | CONTRADICTED / SUPPORTED | lexikalt |
| Samförekomst utan länk | 11 / 11 | 10 / 10 |
| Falskt kompletta | **2** | 2 |
| Godkända bedömningar | 43 / 45 | 30 / 40 |

Jev fixes the period-crossing false complete (`Sekretess regleras
separat` → `INSUFFICIENT`) and the paraphrases. It fails the acceptance
bar on two controls:

- `gäller inte, utom vid sekretessbrott` → `SUPPORTED` (inverterat undantag)
- `punkt 8` + `11. Sekretess` → `SUPPORTED` after the resolved pair

Zero false complete is required. Higher recall is not enough.

Frozen as `baselines/phase2-proof-jev-morph-v1.json`. Does not replace
official C@8 or Coverage v3. Jev is rejected as a standalone proof
evaluator. Do not retune the prompt.

## Proof gate v1

Isolated safety gate. Not Coverage v3 and not C@8. Navigation verifies
referent identity; stacked polarity (`inte` plus `utom`/`dock`/`endast`)
is unresolved. Jev may still judge paraphrases. `SUPPORTED` is admitted
only when the referent matches and polarity is resolved. Otherwise the
evidence stays `UNDECIDED`.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --proof-gate \
  --output ./data/proof-gate-v1.json
```

Optional: pass `--typesafe-api-key` and `--jev-model jev-1.13.0` to score
the four polarity pairs. The reference cases do not use Jev.

Measured live (`jev-1.13.0` on the four polarity pairs only, 1.1 s).
Reference integrity does not call Jev.

| Egenskap | Utfall |
|---|---|
| `punkt 8` mot `11. Sekretess` | blockerad utan Jev |
| `punkt 8` mot `8. Sekretess` | identitet OK |
| Ingen hänvisning mot `8. Sekretess` | blockerad utan Jev |
| `gäller inte vid sekretessbrott` | Jev `SUPPORTED`, grind släpper igenom |
| `gäller även vid sekretessbrott` | Jev `CONTRADICTED` |
| `gäller inte, utom vid sekretessbrott` | Jev `CONTRADICTED`; `SUPPORTED` skulle stoppas |
| `gäller, utom vid sekretessbrott` | Jev `SUPPORTED` |

On the morph suite the inverted exception was `SUPPORTED`. On this
isolated sentence Jev said `CONTRADICTED`. That inconsistency is why
stacked polarity stays unresolved: a later `SUPPORTED` must not complete
the proof. The stop is a class of operators (`inte` plus
`utom`/`dock`/`endast`), not a regex for one sentence.

Frozen as `baselines/phase2-proof-gate-v1.json`. Zero false complete on
these two properties. Not applied to default Coverage v3.

## Coverage v3 + proof gate

Same controller, ranking, C@8 cache, gold, and hop-always proof
evaluation. The only new component sits between that evaluation and
`EVIDENCE_FOUND`. `UNDECIDED` is not `VERIFIED_ABSENT`.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --coverage-v3 \
  --coverage-gold-id liability-secrecy-carveout \
  --coverage-proof-gate \
  --coverage-v3-baseline ./data/coverage-v3.json \
  --output ./data/coverage-v3-gate-carveout.json
```

Measured live (`jev-1.13.0`, 36 s wall).

| Mått | Grind | Officiell v3 |
|---|---:|---:|
| Sanna kompletta vid B5 | **6 / 7** | 7 / 7 |
| Första sju kompletta | aldrig | **150** (B3) |
| Klassificeringar B5 | 482 | 482 |
| Jev-anrop B5 | 184 | 184 |
| Falskt kompletta | **1** (`Avtal_12`) | 1 extra `EVIDENCE_FOUND` |
| Blockerad sann positiv | **Avtal 60** (`UNDECIDED`) | — |
| `BUDGET_EXHAUSTED` | 92, inget relevant | 92, inget relevant |

Avtal 60 is a true carve-out. The YES unit also says `ansvarar inte för
indirekt skada` and later `utom vid … sekretess`. The gate sees stacked
operators in one unit and leaves the document `UNDECIDED`. That is a
quality cost, not a false negative in the classify sense.

Avtal 12 is a termination notice. Hop-always still marks it complete.
The gate does not catch that: it is neither a wrong `punkt N` nor stacked
polarity.

The isolated gate still holds on its two properties. Inside the live
controller it is not enough. Do not retune the polarity class on this
material. Not applied to the default controller.

Frozen as `baselines/phase2-coverage-v3-gate-carveout.json`. Does not
replace official C@8 or Coverage v3.

## Proof found v1

Replay of why hop-always marked `EVIDENCE_FOUND`. No new Jev, embeddings,
or controller. Avtal 12 and Avtal 60 only.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --proof-found \
  --output ./data/proof-found-v1.json
```

| | Avtal 60 | Avtal 12 |
|---|---|---|
| Första Jev YES | C@8 rank 10, `11. Ansvar` | inte i C@8; enda kandidaten är `B9. Slutreglering` |
| Explicit relation i YES | `utom vid … sekretess` (`linked_relation`) | ingen (`not_grounded`) |
| Hop från YES | `PREVIOUS` → `10.2` personuppgiftsbiträde | `PREVIOUS` → `B8. Frivillighet` |
| Regel som slutför | hop-always: YES + hop | hop-always: YES + hop |
| Evidensspan som kan visas | ja, i YES-enheten | nej |
| Grind | `UNDECIDED` (staplad polaritet) | släpper igenom |

Hop-always does not store an evidence span. A hop only adds text. Avtal
60 already contained the relation in the YES unit; the hop to the PUB
clause is not what makes the proof true. Avtal 12 never contained the
relation; YES plus a hop to a notice-period paragraph is enough.

Frozen as `baselines/phase2-proof-found-v1.json`. Does not replace
official C@8 or Coverage v3.

## Proof evidence v1

`EVIDENCE_FOUND` is a completed workflow today. This experiment isolates
a source-grounded proof object so that status cannot be set without a
validated span of the requested relation. No new Jev. Default
controller unchanged.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --proof-evidence \
  --output ./data/proof-evidence-v1.json
```

| Krav | Resultat |
|---|---|
| Sju guldpositiva | `SUPPORTED`, spannet är en exakt delsträng |
| Avtal 60 + PUB-hopp | fortfarande `SUPPORTED`; hoppet skapar inte spannet |
| Avtal 46, cap + undantag | spannet ligger i undantagsenheten |
| Avtal 12 + betänketidshopp | `UNDECIDED` |
| Avtal 49, punkt 4 → infosec | `UNDECIDED` |
| 37 / 47 / 50 / 77 / 78 | `UNDECIDED` |
| Påhittat citat | avvisas |
| Rubrik `8. Sekretess` | inte ett bevis |

Hop-always would still mark Avtal 12 `EVIDENCE_FOUND`. The proof object
does not. Jev YES is a judgment. A hop is retrieval. `EVIDENCE_FOUND`
requires a validated `EvidenceProof`.

A correct span position does not yet prove that the wording expresses
the relation. Inverted exceptions stay visible, not solved. Not applied
to the default controller.

Frozen as `baselines/phase2-proof-evidence-v1.json`. Does not replace
official C@8 or Coverage v3.

## Proof logic v1

Span validation is not relation validation. This experiment represents
polarity and scope as a logical form per predication. Not a gate, not a
parser, no new Jev. Evidence contract and Coverage v3 unchanged.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --proof-logic \
  --output ./data/proof-logic-v1.json
```

| Text | Form |
|---|---|
| `gäller inte vid sekretessbrott` | `cap → does_not_apply → secrecy` |
| `gäller, utom vid sekretessbrott` | `cap → does_not_apply → secrecy` |
| `gäller inte, utom vid sekretessbrott` | `cap → does_not_apply → other → except secrecy` |
| Avtal 60, two sentences | claim form in sentence 2; not inverted |
| `undantas från ansvarsbegränsningen` | `undecided` |
| Avtal 12 / `8. Sekretess` | `undecided` |

The unit-level polarity gate marked Avtal 60 unresolved because `inte`
and `utom` share a TextUnit. Per predication they do not share a
sentence. The inverted pair is source-grounded and Jev called it
`SUPPORTED`. Quote plus YES is still not a proof.

Operator-visible polarity can be represented. Paraphrases stay
`undecided` here; frozen Jev synonym recall remains 1.0. That ability
is not a proof. Not applied to the default controller.

Frozen as `baselines/phase2-proof-logic-v1.json`. Does not replace
official C@8 or Coverage v3.

## Proof predicate v1

Jev does not decide `SUPPORTED`. Code proposes candidate predications.
Jev picks operator, object, and span. Structure admits `verified` only.
`proposed` is not `EVIDENCE_FOUND`. No new controller. Evidence contract
unchanged.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --jev-model jev-1.13.0 \
  --proof-predicate \
  --output ./data/proof-predicate-v1.json
```

Measured live (`jev-1.13.0`, 46 judgments).

| Mått | Resultat |
|---|---|
| Parafraser, rätt operator | **10 / 10** (7 `proposed`, 3 `verified`) |
| Inverterat undantag | `inverted`, bekräftat, inte `EVIDENCE_FOUND` |
| Avtal 60 | mening 2, `verified` |
| Samförekomst utan relation | `none` |
| Fel klausul (punkt 8 → 11) | object `other`, inte rubrik 11 |
| Matchande sekretessrubrik | `proposed`, inte funnen |
| Falskt kompletta | **0** |
| Tier | 11 verified / 17 proposed / 18 insufficient |

Jev extracted the inverted operator that the old YES/NO proof-eval
missed. It also extracted every paraphrase. Those paraphrases stay
`proposed`. A pointer to `punkt N` comes back as `does_not_apply` +
`other`, not as a completed secrecy carve-out.

The model proposes relations. Only verified relations may become
lasting facts. Not applied to the default controller.

Frozen as `baselines/phase2-proof-predicate-v1.json`. Does not replace
official C@8 or Coverage v3.

## Proof proposed v1

The 17 `proposed` rows are not one leftover. No new Jev. Do not loosen
`verified`.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --proof-proposed \
  --output ./data/proof-proposed-v1.json
```

| Orsak | Antal | Mer information verifierar? |
|---|---:|---|
| Parafras utan observerbar operator | 7 | nej |
| Annan juridisk relation (`applies`) | 7 | nej |
| Hänvisning löst, men spannet är inte relationen | 3 | nej |
| Ofullständig hänvisning | 0 | — |
| Tvetydig formulering | 0 | — |

**0 / 17** would become a verified claim by more graph hops.

The seven applies cases must not support the carve-out claim. The seven
paraphrases need semantic verification, not a wider rule. The three
after-navigation cases already have the referent; it is a heading or a
duty, not a carve-out span.

Unresolved `punkt N` pointers that Jev left as `does_not_apply` +
`other` are already `insufficient`, not `proposed`. Those are the cases
where navigation is the next step. When navigation only finds a heading
or a duty, the result stays undecided.

Do not make `verified` easier to raise recall. Frozen as
`baselines/phase2-proof-proposed-v1.json`. Does not replace official C@8
or Coverage v3.

## Blind carve-out gold v1

Error analysis of property E on `contracts_v2` gold. No new Jev. Seen
detectors unchanged. Gold is synthetic.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --blind-carveout \
  --output ./data/blind-carveout-gold-v1.json
```

`LINK_RE` and claim-form match **0 / 53** gold YES quotes. They also
match 0 / 39 gold NO quotes. They match two UNCERTAIN rows where the
sentence names secrecy but the number points elsewhere
(`avtal_138`, `avtal_173`). Those are the only LINK_RE hits in the
whole E set.

28 / 53 YES quotes contain no secrecy word at all. They point at a
heading. 34 / 53 are multi-clause. The new wording uses tystnadsplikt,
Konfidentiell/Förtrolig Information, "Inget i denna punkt ska
begränsa", "Detsamma gäller", and letter lists. That is why predicate
completed 0 / 53 on the live blind run.

Gold NO traps that would fool hop-always + Jev YES are
co-occurrence (7), topical GDPR/infosec, inverse/negation,
wrong referent, and precedence/supersession. The live false-complete
document list is not in this checkout. Do not loosen `verified`.

Frozen as `baselines/phase2-blind-carveout-gold-v1.json`. Does not
replace official C@8 or Coverage v3.

## Decision traces v1

The blind coverage run that named five false completes is not in this
checkout. Existing coverage JSON keeps document paths, not the
TextUnits, hops, or the reason `EVIDENCE_FOUND` was set. Do not guess
those documents from gold traps.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --inspect-decision-trace \
  --output ./data/decision-trace-v1.json
```

A later Coverage v3 run can record the missing traces without changing
the retriever, C@8, `LINK_RE`, or the default stop rule:

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --coverage-v3 \
  --coverage-gold-id liability-secrecy-carveout \
  --decision-trace \
  --output ./data/coverage-v3-decision-trace.json
```

Each found document then has: document id, query, an ordered event
list (`classify` → `navigation` → complementary units →
`proof_decision`), Jev YES units, hops, all units used, controller
status before the first hop, whether `LINK_RE` already matched the
source text, why the controller completed, the gold span if the
document is relevant, and an error class only when gold supplies one.
Each unit carries `key`, `node_id`, offsets, and text hashes so the
same span can be reopened after the run.

Tracing does not change candidate selection or `EVIDENCE_FOUND`.
UNCERTAIN gold must not be counted as a false complete.

Live frozen v3 on contracts_v2 carve-out (`jev-1.13.0`, 31 s): **39 / 53**
complete positives at B5. Five non-relevant completes: two gold NO
(`avtal_119`, `avtal_200`, both precedence override) and three
UNCERTAIN (`avtal_138`, `avtal_142`, `avtal_173`). Do not pad the
false-complete set to five. Every complete decision was
`jev_yes_after_hop`. `LINK_RE` matched only the two falsa-demonstratio
UNCERTAIN rows. Frozen as
`baselines/phase2-coverage-v3-blind-trace-v1.json`. No new proof rule.

## Proof requirements v1

Observed traces, not a new engine. Gold tests **prevailing terms**, not
whether a carve-out formulation exists somewhere. Default v3 is
unchanged.

| `EVIDENCE_FOUND` | Antal |
|---|---:|
| Gold YES | 39 |
| Gold NO | 2 |
| Gold UNCERTAIN | 3 |

The 39 matching documents are not 39 verified proofs. The two gold NO
rows are `avtal_119` and `avtal_200`. The three UNCERTAIN rows stay
unresolved; they are not false completes and not verified.

Three regression requirements, all unsatisfied by hop-always:

1. An explicit amendment of the cited provision must not be ignored.
2. A missing link must be resolved by the cited material, not any hop.
3. An existing sentence, anaphor, or list link may be used without
   obligatory navigation.

Rejected fixes: NO always wins, first or last model answer wins, any
successful hop, joining nearby units, forcing UNCERTAIN to NO.

The unmapped gold quote is `avtal_160` (`☒` plus an extra space). That
is a contains-mapping miss, not a ranking miss. Gold-map v2 locates it
without changing the source text; historical v1 measurements stay.

Proof evaluation can test that a conclusion is supported by the examined
material and that a read amendment was handled. It cannot, from those
chains alone, prove that the whole document was examined and that no
further provisions affect the conclusion. Not having seen an amendment
is not proof that none exists.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --proof-requirements \
  --output ./data/proof-requirements-v1.json
```

Frozen as `baselines/phase2-proof-requirements-v1.json`. Does not
replace official C@8 or Coverage v3. Do not build a general chain
engine from this file.

Frozen as `baselines/phase2-decision-trace-v1.json`. Does not replace
official C@8 or Coverage v3. Do not loosen `verified`. Do not add
synonyms to `LINK_RE`.

## Gold-map v2

Corrected evaluation of gold `contains`. Historical v1 exact matching
is unchanged. Official C@8 and Coverage v3 are unchanged.

Locate: if the gold snippet is not an exact substring, collapse runs
of space and non-breaking space only. Do not collapse newlines, tabs,
ballot marks, or negations.

Ground: map the collapsed hit back to the original unit text. Store
that excerpt and its offsets, including the two spaces after `☒` in
`avtal_160`. Do not rewrite the document to fit gold.

If several hits remain, report the ambiguity. Do not pick one.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --gold-map-v2 \
  --output ./data/gold-map-v2.json
```

Frozen as `baselines/phase2-gold-map-v2.json`. A mapping correction is
not a proof-evaluation improvement.

## Decision contract v1

Both the hop-always reference and the new contract are scored with
gold-map v2. The historical v3 report is unchanged. Navigation is used
when the chain lacks a required part; a hop is not an approval.

The new contract is:

`candidate → source-grounded evidence chain → assessment against the
question's explicit proof requirements`

It does not continue `Jev YES → hop → EVIDENCE_FOUND → more filters`.
A well-formed proof is reviewable; it is not automatically correct.

| Variant | True support | False approvals | Repaired UNCERTAIN | Leftover genuine |
|---|---:|---:|---:|---:|
| Hop-always (reference) | 39 | 2 | 3 | 14 |
| Grounded chain | 12 | 0 | 0 | 41 |

The 39 hop-always documents are correct gold outcomes, not 39 shown
proof chains. The chain contract did not lose 27 verified proofs; it
approved 27 fewer positive documents. Zero false approvals must be
read together with that abstention.

Examined-material support is not a complete document investigation.
Every replayed decision stays `PARTIAL`. An approved chain does not
upgrade coverage to `COMPLETE`.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --decision-contract \
  --output ./data/decision-contract-v1.json
```

Frozen as `baselines/phase2-decision-contract-v1.json`. Does not
replace official C@8 or Coverage v3. Do not loosen `verified`.

## Clause resolve v1

Explicit clause citations in the evidence chain. Not a return to
required hops, not a general anaphor or paraphrase solver. Finding
the cited clause is not admission. Both variants use gold-map v2.
Known cases are regression tests, not a blind test.

Avtal 103 is the positive target: resolve avsnitt 4 and test the
relation against that section. Avtal 138 and 173 are controls: a
conflicting reference must not be repaired by picking another
secrecy clause.

| Variant | True support | False approvals | Leftover genuine | Extra units |
|---|---:|---:|---:|---:|
| Grounded chain | 12 | 0 | 41 | 0 |
| + clause resolve | 15 | 0 | 38 | 24 |

Undecided passages stay searchable with source spans. They are not
decided prevailing-terms conclusions. Approved chains remain
`PARTIAL`.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --clause-resolve \
  --output ./data/clause-resolve-v1.json
```

Frozen as `baselines/phase2-clause-resolve-v1.json`. Does not replace
official C@8 or Coverage v3.

## Anaphor and list v1

Isolated discourse links. Do not concatenate units. The antecedent or
list intro is identified, then the relation is tested against that
predication. Finding the antecedent is not admission.

Avtal 106 anchors *Detsamma gäller* to the previous sentence in the
same unit, not the Dataskydd hop. Avtal 107, 171, 175 and 176 anchor
*Samma sak* / *Detsamma* to the previous unit's exception. Avtal 140
anchors list item (c) to *gäller inte i följande fall*. A secrecy
exception list is not the claim.

Both variants use gold-map v2. Known cases are regression tests.

| Variant | True support | False approvals | Leftover genuine | Extra units |
|---|---:|---:|---:|---:|
| + clause resolve | 15 | 0 | 38 | 0 |
| + anaphor/list | 19 | 0 | 34 | 0 |

Ability curve (hop-always is gold outcomes, not verified proofs):

| Experiment | Underbyggda YES | Falska godkännanden |
|---|---:|---:|
| Hop-always | 39* | 2 NO + 3 UNCERTAIN |
| Evidenskedja | 12 | 0 |
| + Klausuluppslag | 15 | 0 |
| + Anaforer/listor | 19 | 0 |

Approved chains remain `PARTIAL`. Retrieval and Jev C@8 are unchanged.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --anaphor-resolve \
  --output ./data/anaphor-list-v1.json
```

Frozen as `baselines/phase2-anaphor-list-v1.json` and
`baselines/phase2-ability-curve-v1.json`. **19/53 is the
experimental quality reference.**

### Leftover diagnosis (34 genuine YES)

No new Jev. Does not start the next ability. Same document may
belong to several classes. Coverage v3 and C@8 are unchanged.

First split: 20 examined but undecided, 14 never examined.

| Felklass | Dokument |
|---|---:|
| Parafraser | 10 |
| Ändringsbestämmelser | 2 |
| Rangordning mellan dokumentdelar | 5 |
| Definierade termer | 2 |
| Andra olösta kopplingar | 21 |

Unlock if one examined ability is added. Ranked by effect, not ease:

| Enskild förmåga | Avgörbara dokument |
|---|---:|
| Undantagsparafras (`omfattar inte`, högre tak) | 7 |
| Citatetikett (`artikel`, `klausul`, romerska tal) | 5 |
| Klausulnumrering (`§` i rubrik) | 2 |
| Rubrikhänvisning | 1 |
| Definierade termer | 1 |
| Dokumentrangordning | 1 |

Three unexamined documents (135, 159, 168) would already be
decidable with the current anaphor and in-unit link abilities if
coverage found them. Three examined documents (120, 137, 194)
need two abilities.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --leftover-diagnosis \
  --output ./data/leftover-diagnosis-v1.json
```

Frozen as `baselines/phase2-leftover-diagnosis-v1.json`.

### Ability review (before the next ability)

Independent review of the live proof stack. Does not start A or B.
Does not change Coverage v3 or C@8. 19/53 remains the quality
reference.

The live decision path is three modules and is not wired into v3:

`assess_chain` → `assess_with_clauses` → `assess_with_anaphors`.

Hypothesis A (table count 7) is three constructions, not one
ability: five identical `omfattar inte` sentences, one higher cap,
and one double negation. Do not expand `EXCEPTION_RE` or
`LINK_RE`. The frozen predication model is not ready; it still
classifies via rejected `LINK_RE`.

Hypothesis B (5) is one gap. The source already has
`EXCEPTION_RE` or `NOTHING_LIMITS_RE`. The texts are not parsed
as citations (`artikel`, `klausul`, roman digits), so the clause
layer never runs. If implemented later: one parser, keep citation
kind in lookup, finding the clause is not admission.

135, 159 and 168 remain discovery regressions. The bench must
decide between A and B. Neither is applied to the default
controller.

Frozen as `baselines/phase2-ability-review-v1.json`.

### Static review (read-only)

Accepted findings from the independent source reading. Does not
change v3. Does not start the next ability.

Coverage v3 `COMPOSITE` can still become `EVIDENCE_FOUND` after
Jev YES plus a hop. `admit_evidence_found` is not on that path.
19/53 is therefore an experimental curve, not v3 verification.
Zero false approvals is shown on the frozen fixtures, not on a
broader population.

Frozen as `baselines/phase2-static-review-v1.json`.

### Experiment principles

v3 stays frozen. The experimental chain stays 19/53 on frozen
material. Future proof evaluation is not decided. Existing gold
and C@8 fallbacks are left in place, but they are measurement
defects: official comparisons must name the C@8 baseline, and a
quality metric must say if evidence was supplied from gold.

New legal formulations are tested without first adapting the
rules. Experimental proof modules are not production
architecture. Search is closer to done than legal verification.

Frozen as `baselines/phase2-experiment-principles-v1.json`.

### Citation labels

Isolated parser experiment. Does not change `cited_relation_holds`.
`artikel` is not `§`. Roman is not arabic. Coverage v3 and C@8
are unchanged. Independent formats and negatives are tested
before the leftover five are counted.

| Variant | True support | False approvals | Leftover genuine | Extra units |
|---|---:|---:|---:|---:|
| + anaphor/list | 19 | 0 | 34 | 0 |
| + citation labels | 24 | 0 | 29 | 29 |

118, 125, 141, 153 and 179 become supported. 120 stays
undecided: the artikel is found, the higher-cap source fails the
existing relation test. 138 and 180 stay undecided.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --citation-labels \
  --output ./data/citation-label-v1.json
```

Frozen as `baselines/phase2-citation-label-v1.json`. **24/53 is
the new experimental quality reference.** 19/53 remains the
anaphor-list reference.

### Leftover 29 after citation labels

Measured, not derived: 15 examined and undecided, 14 never
examined. Does not start the next ability. Does not add another
parser rule.

| Track | Documents |
|---|---:|
| Semantic understanding | 10 |
| Discovery / never examined | 14 |
| Remaining structure | 4 |
| Needs two abilities | 1 |

120 and 194 now have a unique artikel; they stay undecided
because the source is a higher cap. 135, 159 and 168 would
already be decidable with current abilities if coverage found
them. The fork is semantics versus discovery.

Frozen as `baselines/phase2-leftover-29-v1.json`.

### Discovery diagnosis of the 14

24/53 stays frozen. No new controller, retrieval change, or
Jev. The 14 leftover YES that never reached proof evaluation
are scored from the saved Coverage v3 B5 trace plus a replay of
the same hybrid RRF ranking and gold-map v2 locate.

| Cause | Documents |
|---|---:|
| Never in global_k=50 | 7 |
| Wrong passage in the seed | 5 |
| Gold seeded, budget exhausted | 1 |
| Gold seeded, navigation miss | 1 |

12/14 are a ranking problem. Only 121 and 127 had the gold
passage in the seed. 114, 168, 169 and 181 still received later
per-document budget outside the seed. 135, 159 and 168 would
already be decidable with current abilities if found; all three
are outside the seed. This does not choose the next action.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --discovery-diagnosis \
  --openai-api-key "$OPENAI_API_KEY" \
  --output ./data/discovery-diagnosis-v1.json
```

Frozen as `baselines/phase2-discovery-diagnosis-v1.json`.

### Two-stage retrieval at a fixed candidate budget

24/53 stays frozen. No Jev, no controller, no proof change.
Same embeddings and the same hybrid RRF scores. Intra-document
order matches the global ranking filtered to one document, so
any change is budget allocation, not a better clause ranker.
Structure-guided local search is not started.

Stage 1 is document identification (first unique document in
the global list). Stage 2 is the local passage rank of the gold
span. Candidate lists are compared at a fixed total of 50.

| Strategy | Unique docs | Leftover doc-recall | Leftover passage-recall | 135/159/168 |
|---|---:|---:|---:|---|
| Global top-50 | 45 | 7/14 | 2/14 | none |
| Two-stage 50×1 | 50 | 7/14 | 1/14 | none |
| Two-stage 25×2 | 25 | 3/14 | 2/14 | none |
| Two-stage 10×5 | 10 | 0/14 | 0/14 | none |
| Two-stage 5×10 | 5 | 0/14 | 0/14 | none |

Local gold ranks are 1–10. 155 is identified 16th and its gold
is local rank 10 (global 728). 135, 159 and 168 need document
identification 88, 51 and 72. A 50-slot list cannot select
those documents. 10×5 examines ten other contracts; none of the
14 leftover YES are among the first ten identified documents.

```bash
uv run overgraph-ingest \
  --db ./data/blind-overgraph \
  --dense-dimension 3072 \
  --two-stage-retrieval \
  --openai-api-key "$OPENAI_API_KEY" \
  --output ./data/two-stage-retrieval-v1.json
```

Frozen as `baselines/phase2-two-stage-retrieval-v1.json`.

### Workspace inventory stop

Two-stage is a negative experiment. Reallocating the same 50
candidates does not complete a workspace inventory. Do not start
another two-stage run. Do not build a new document ranking on
the same 100 synthetic contracts.

The same passage score is used for two tasks: which documents
may contain the answer, and where in a document the answer is.
155 is identified 16th with local gold rank 10. 135 has local
gold rank 2 but is identified 88th. Those are separate limits.

A global top-50 list is not a completeness guarantee. That does
not require Jev on every document. It does require a separate
way to handle documents with no relevant hit.

Two independent quality limits remain:

| Limit | Kind | Open |
|---|---|---:|
| Discovery | information selection | 14 unexamined |
| Proof evaluation | legal understanding | 15 examined, undecided |

24/53 stays the experimental quality reference. Ingest-time
property extraction is unmeasured and not started. It is not
assumed right for composite legal relations.

Frozen as `baselines/phase2-workspace-inventory-v1.json`.

### Cerebras rerank

Separate from Jev, Coverage v3, and the experimental proof
chain. Hybrid top-50, one synchronous Cerebras `gpt-oss-120b`
call per question, 50 clauses in one prompt. The task is
formulation presence, not prevailing terms. Invented IDs fail.
UNCERTAIN is not MATCH. 24/53 stays the proof reference.

| Gold | Precision | Candidate-recall | Corpus-recall | Doc-recall | MATCH | UNCERTAIN | Model s |
|---|---:|---:|---:|---:|---:|---:|---:|
| auto-renewal | 1.00 | 1.00 | 1.00 | 1.00 | 20 | 1 | 1.55 |
| notice-period | 0.55 | 1.00 | 0.85 | 0.85 | 20 | 0 | 1.70 |
| liability-cap | 0.90 | 1.00 | 0.82 | 0.89 | 31 | 5 | 3.13 |
| confidentiality | 0.29 | 1.00 | 0.46 | 0.46 | 21 | 6 | 1.92 |
| secrecy-carveout | 1.00 | 1.00 | 1.00 | 1.00 | 7 | 0 | 1.68 |

Candidate-recall is 1.0 on all five: every gold clause that
reached the top-50 was selected. Corpus gaps are retrieval
(notice-period 11/13, liability-cap 28/34, confidentiality
6/13). Confidentiality over-selects. Mean TTFT 1.44 s, mean
model 2.00 s, five questions in 19.4 s wall. API cost was not
returned. This is not C@8 and not verified proof.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-rerank \
  --cerebras-k 50 \
  --openai-api-key "$OPENAI_API_KEY" \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --output ./data/cerebras-rerank-v1.json
```

Frozen as `baselines/phase2-cerebras-rerank-v1.json`.

### Cerebras output size

Same five seen golds, same frozen hybrid top-50, same
`gpt-oss-120b`. Variant A is the reasoned freeze above.
Variant B asks only for MATCH and UNCERTAIN ids. Omitted ids
are NO_MATCH. No new retrieval. No k=100. C@8 stays frozen.

| Gold | B precision | B recall | B MATCH | B UNCERTAIN | B completion | A completion | Δ tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| auto-renewal | 1.00 | 1.00 | 20 | 1 | 1962 | 2458 | −496 |
| notice-period | 0.55 | 1.00 | 20 | 0 | 1563 | 2519 | −956 |
| liability-cap | 0.82 | 1.00 | 34 | 2 | 2820 | 3074 | −254 |
| confidentiality | 0.30 | 1.00 | 20 | 0 | 1702 | 2888 | −1186 |
| secrecy-carveout | 1.00 | 1.00 | 7 | 0 | 1541 | 2932 | −1391 |

Candidate-recall stayed 1.0. Zero invented or duplicate ids.
Mean model latency 1.33 s vs 2.00 s. Five questions in 6.73 s
wall because B does not re-retrieve. Completion tokens fell
from 13 871 to 9 588 (−31 %), not to the size of the JSON
(hundreds of characters). The billed completion is still
internal work, not the visible id list.

Liability-cap precision fell 0.90 → 0.82 because three former
UNCERTAIN ids became MATCH. The other four questions kept
their MATCH counts or dropped false positives. Minimal output
kept selection quality on this set. It did not make the call
near-instant.

Do not present B as verified legal conclusions. Do not switch
the reasoned freeze. Do not start k=100 from this result.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-output \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --output ./data/cerebras-output-v1.json
```

Frozen as `baselines/phase2-cerebras-output-v1.json`.

### Cerebras Qwen

Same five seen golds, same frozen hybrid top-50, same
minimal MATCH/UNCERTAIN JSON as output v1. One synchronous
`qwen-3.8-27b` call per question. Unset Qwen reasoning spent
40 000 completion tokens on the first question and emitted no
JSON. The measured run therefore sets `reasoning_effort=low`
and keeps the 8192 cap. Formulation presence, not proof.
C@8 and both gpt-oss freezes stay.

| Gold | Qwen P | B P | Qwen recall | Qwen MATCH | Qwen UNCERTAIN | Qwen completion | Qwen reasoning | Cost USD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| auto-renewal | 0.95 | 1.00 | 1.00 | 21 | 0 | 3164 | 3071 | 0.0088 |
| notice-period | 0.55 | 0.55 | 1.00 | 20 | 15 | 3892 | 3744 | 0.0094 |
| liability-cap | 0.88 | 0.82 | 1.00 | 32 | 2 | 3601 | 3457 | 0.0089 |
| confidentiality | 0.29 | 0.30 | 1.00 | 21 | 6 | 2446 | 2330 | 0.0079 |
| secrecy-carveout | 1.00 | 1.00 | 1.00 | 7 | 2 | 1136 | 1092 | 0.0044 |

Candidate-recall stayed 1.0. Zero invented or duplicate ids.
Mean precision 0.733 vs B 0.735. Mean model 1.97 s vs B 1.33 s.
Five questions in 9.92 s wall. Prompt 18 258, completion
14 239, of which 13 694 are reasoning tokens. Visible JSON is
still hundreds of characters. Cost from the 2026-10-09
Developer rate card: Qwen $0.039 vs gpt-oss B $0.013. The API
does not return USD.

Rejected for naive rerank, the same way BGE-M3 was
rejected for retrieval. GPT-OSS output v1 stays the best
naive baseline. Qwen is not cheaper or faster. Default
reasoning is unusable here. Do not present the ids as
verified legal conclusions. Do not replace output v1.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-qwen \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --output ./data/cerebras-qwen-v1.json
```

Frozen as rejected in `baselines/phase2-cerebras-qwen-v1.json`.

### Cerebras reasoning

Same five seen golds, same frozen hybrid top-50, same
minimal JSON, same `gpt-oss-120b`. Current is output v1
(unset, API default medium). It was not re-run. The API
rejects `none`, `off`, and `minimal`. Lowest supported
effort is `low`. Hard and watch negatives are scored
separately. C@8 and output v1 stay.

| Gold | Curr P | Low P | Curr recall | Low recall | Hard MATCH | Watch MATCH | Curr completion | Low completion |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| auto-renewal | 1.00 | 1.00 | 1.00 | 1.00 | 0/1 | 0/1 | 1962 | 747 |
| notice-period | 0.55 | 0.55 | 1.00 | 1.00 | — | 1/1 | 1563 | 755 |
| liability-cap | 0.82 | 0.71 | **1.00** | **0.89** | 1/1 | 2→0 | 2820 | 402 |
| confidentiality | 0.30 | 0.27 | 1.00 | 1.00 | — | 2/2 | 1702 | 512 |
| secrecy-carveout | 1.00 | 1.00 | 1.00 | 1.00 | 0/1 | 0/2 | 1541 | 317 |

`low` cut completion from 9 588 to 2 733 (−71 %) and cost
from $0.013 to $0.0077. Mean model 1.33 s → 1.01 s. Five
questions in 5.23 s wall. Candidate-recall is no longer 1.0:
liability-cap missed three gold clauses that current kept.
Hard-negative accepts stayed at one (GDPR statutory
allocation on liability-cap). The explicit auto-renewal
negation in the list was rejected by both. Watch-negative
accepts fell 5 → 3.

Reasoning cannot be turned off on this model. Lowest
effort is cheaper and faster. It is not equivalent on
recall. Do not replace output v1.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-reasoning \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --output ./data/cerebras-reasoning-v1.json
```

Frozen as `baselines/phase2-cerebras-reasoning-v1.json`.

### Cerebras medium chosen

Stop tuning model parameters on the same five questions.
GPT-OSS-120B medium plus minimal JSON is the best measured
quality setting for naive rerank. Low is cheaper, not
quality-equivalent. Qwen is rejected for this task. k=200
and second opinion are not started.

Frozen as `baselines/phase2-cerebras-medium-chosen-v1.json`.

### Cerebras k=100

Same five seen golds, same hybrid scorer, GPT-OSS medium,
minimal JSON. k=50 was not re-selected. The recomputed
top-50 matched the frozen lists exactly (overlap 50/50).
That keeps retrieval gain separate from ranking drift.

| Gold | Relevant @50 | Relevant @100 | Gain | Still missing | Corpus-recall @100 |
|---|---:|---:|---:|---:|---:|
| auto-renewal | 20 | 20 | 0 | 0 | 1.00 |
| notice-period | 11 | 11 | 0 | 2 | 0.85 |
| liability-cap | 28 | **34** | **6** | 0 | **1.00** |
| confidentiality | 6 | 7 | 1 | 6 | 0.54 |
| secrecy-carveout | 7 | 7 | 0 | 0 | 1.00 |

Retrieval@100 improves mean corpus-recall from 82.6 % to
87.7 %. Seven more gold clauses appear, six of them on
liability-cap. Notice-period and most of confidentiality stay
outside the top-100. Retrieval is doing what it should:
returning more candidates when asked for more. Ranking is
still thin on confidentiality.

A first attempt to classify all 100 candidates in one
GPT-OSS Medium call failed because the reasoning budget ran
out. The model did not choose the wrong clauses. It never
emitted JSON. Candidate-recall and precision at one-shot
k=100 are therefore unmeasured. That is not evidence that
GPT-OSS cannot handle 100 candidates.

The working k=50 cap is 8 192 completion tokens. The first
one-shot call exhausted that cap on reasoning. The runner
then raised the *measurement* cap to 40 000 to see whether
more room would produce JSON. It did not: 39 997 reasoning
tokens, `finish_reason=length`, empty content, $0.032 for
that single failed call versus $0.013 for all five questions
at k=50. The 40 000 figure is a diagnostic raise, not the
working setting and not a silent fallback.

Do not switch to low to force a JSON. Do not treat one
failed one-shot as a batch-size limit. Do not start k=200.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-k100 \
  --openai-api-key "$OPENAI_API_KEY" \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --output ./data/cerebras-k100-v1.json
```

Frozen as `baselines/phase2-cerebras-k100-v1.json`.

### Cerebras split-50

Same five seen golds, same hybrid top-100, GPT-OSS medium,
minimal JSON, working 8 192 cap. Each question is two
sequential calls of 50. This is not Jev batching, not a
one-shot retry, and not a reasoning change. Top-50 overlap
with the frozen lists stayed 50/50. k=200 and second
opinion stay unstarted.

All ten calls completed and returned JSON.

| Gold | P | Recall@100 | True | First50 lost gold | Second50 true | Second50 MATCH | Model s |
|---|---:|---:|---:|---:|---:|---:|---:|
| auto-renewal | 1.00 | 1.00 | 20 | 0 | 0 | 0 | 2.21 |
| notice-period | 0.48 | 1.00 | 11 | 0 | 0 | 3 | 2.51 |
| liability-cap | 0.67 | 1.00 | 34 | 0 | 6 | 16 | 3.70 |
| confidentiality | 0.19 | 1.00 | 7 | 0 | 1 | 16 | 3.13 |
| secrecy-carveout | 1.00 | 1.00 | 7 | 0 | 0 | 0 | 2.99 |

Candidate-recall over the 100 is 1.0. The model caught all
seven retrieval-gain clauses and dropped none of the 72
previously correct gold matches. Two extra first-50 false
positives appeared (liability-cap +1, confidentiality +1).
The first-50 selection otherwise held.

Mean precision fell 0.735 → 0.667. That drop is almost
entirely the second 50: notice-period added 3 MATCH with no
gold there; liability-cap 16 MATCH / 6 gold; confidentiality
16 MATCH / 1 gold. Auto-renewal and carve-out stayed quiet
on the second 50.

Prompt 33 251, completion 17 246, reasoning 16 212. Cost
$0.025 versus $0.013 for output v1. Cost per true match
$0.00031 versus $0.00018. Mean model time 2.91 s for the
two calls versus 1.33 s for one k=50 call. Five questions
in 21.87 s wall. Zero invented or duplicate ids.

Two calls of 50 completed under the working cap. One one-shot
of 100 did not. That measures batch size, not a new model or
controller. Formulation presence, not proof. Do not start
k=200 from this result.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-split50 \
  --openai-api-key "$OPENAI_API_KEY" \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --output ./data/cerebras-split50-v1.json
```

Frozen as `baselines/phase2-cerebras-split50-v1.json`.

### Cerebras modes

1×50 remains the fast naive baseline. 2×50 is a successful
scale mode: seven more gold clauses, lower precision, almost
double the cost. Do not add automatic routing between them.
Do not start k=200.

Frozen as `baselines/phase2-cerebras-modes-v1.json`.

### Cerebras second opinion

Replay only. Same gold-map v2. No new Jev calls, no new
Cerebras calls, no router. Official C@8 supplies auto-renewal;
the other four golds use their C@8 live files. GPT-OSS labels
come from output v1.

The hybrid top-50 lists are not identical. Overlap is 233 of
250 candidate slots (45–49 per question). 17 keys are Jev-only
and 17 are Cerebras-only. Only the intersection is compared.

| Gold | Overlap | Jev errors | Corrected | Worsened | Same error | Jev UNCERTAIN | UNCERTAIN resolved |
|---|---:|---:|---:|---:|---:|---:|---|
| auto-renewal | 45 | 2 | 2 | 0 | 0 | 5 | 5/0 |
| notice-period | 46 | 5 | 0 | 3 | 5 | 0 | — |
| liability-cap | 48 | 6 | 2 | 2 | 4 | 0 | — |
| confidentiality | 45 | 14 | 4 | 2 | 10 | 3 | 3/0 |
| secrecy-carveout | 49 | 0 | 0 | 0 | 0 | 1 | 1/0 |

On the overlap: 27 Jev errors, 8 corrected, 7 worsened, 19
the same error, 0 mixed shared errors. Net +1. Both models
are already correct on 188 of 233 keys.

GPT-OSS fixes both known auto-renewal C@8 mistakes. It does
not help notice-period: zero corrections and three new false
positives. Confidentiality stays the weak question; ten of
fourteen Jev errors are also Cerebras errors.

Jev UNCERTAIN is a safe second-opinion slice: 9/9 resolved
correctly, all true negatives. Replacing those abstentions
does not change precision or recall. The hard Jev errors are
mostly shared false positives, not UNCERTAIN.

Rescored mean precision 0.752 (Jev) versus 0.747 (GPT-OSS).
Recall 0.99 versus 1.00. That is not a reason to replace C@8
or to build a router. Formulation presence, not proof.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-second-opinion \
  --output ./data/cerebras-second-opinion-v1.json
```

Frozen as `baselines/phase2-cerebras-second-opinion-v1.json`.

### Second opinion rejected

GPT-OSS is rejected as a general second opinion on Jev. Net +1
on 233 overlapping keys. 19 of 27 Jev errors are shared.
Disagreement is not an uncertainty signal. Jev UNCERTAIN does
not steer escalation. Do not build a model router. Jev C@8
remains the classify reference.

Frozen as rejected in
`baselines/phase2-cerebras-second-opinion-rejected-v1.json`.

### Phase close

The bench now separates three jobs: fast clause search,
document coverage, and legal proof evaluation. That split is
the result of the original “200 contracts quickly” goal.

Consider for Socialism, without starting the transfer here:
sequential DOCX ingest, hybrid openai-tfidf search, and Jev
C@8 classify.

Keep as research: Coverage v3, the experimental proof stack,
and Cerebras naive rerank.

Rejected: second-opinion escalation, Qwen, BGE-M3, Jaccard
routing, Jev prompt-batching, and Jev as standalone proof.

Do not start k=200, a model router, automatic k routing, or a
default-controller change from this close.

Frozen as `baselines/phase2-phase-close-v1.json`.

### Tabular Review v1

New experiment. One question, one document, one
source-grounded cell. Not Coverage v3 and not a legal
proof engine.

Reuse OverGraph hybrid ranking, Jev classify, hop
mechanics, clause lookup, and `validate_span`. Do not
import hop-always, `EVIDENCE_FOUND`, or
`VERIFIED_ABSENT`.

Three variants share document-local hybrid retrieval
at `k=5`. Recall is also recorded at k=3 and k=10
without extra model calls.

| Variant | Model | Navigation |
|---|---|---|
| A | Jev | Adaptive, only when Jev names a concrete need |
| B | Jev | None |
| C | GPT-OSS Medium | None |

Allowed cell statuses: `ANSWERED`, `UNCERTAIN`,
`NOT_FOUND`. `ANSWERED` needs a validated excerpt.
A hop is never itself an answer. Exhausted budget
becomes `UNCERTAIN`, not verified absence. Invalid
references are reported, not substituted.

First run: frozen 20 documents × 5 user questions =
100 cells × 3 variants, fully synchronous. The set
is diagnostic and gold-balanced; it is not a general
Tabular Review quality score. The 100-document run
is not started. Cell accuracy is not comparable to
leftover `24/53`. Answer correctness and citation
correctness are scored separately. A validated
excerpt is not by itself a correct legal answer.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --tabular-review \
  --output ./data/tabular-review-v1.json
```

Measured on the diagnostic 20×5 set (27 gold-positive
cells of 100). Not a general quality score.

| Mått | A Jev+nav | B Jev | C GPT-OSS |
|---|---:|---:|---:|
| Cell accuracy | 0.77 | **0.78** | 0.71 |
| Answer accuracy | 0.80 | **0.81** | 0.74 |
| Citation accuracy | 0.53 | **0.54** | 0.48 |
| Citation grounded | 1.00 | 1.00 | 1.00 |
| Seconds/cell p50 | 1.74 | 1.62 | **0.47** |

Jev requested navigation in 0/100 A-cells. A did not
beat B. Cerebras did not beat Jev. Confidentiality is
the weak question: many grounded quotes that are not
the gold unit. Carveout can cite the right sentence
and still be the same sentence reused for the wrong
question.

Cerebras cost about $0.051 per 100 C-cells. Jev USD
is unknown; 1 244 Jev calls and 100 Cerebras calls
for the 300-cell table. Wall 396s.

Frozen as `baselines/phase2-tabular-review-v1.json`.
The 100-document run is not started.

### Tabular Qwen Low

Isolated replay of the same 100 frozen C-cells from
tabular v1. Same candidate keys. No new retrieval and
no navigation. `qwen-3.8-27b` with `reasoning_effort=low`
and the same cell JSON as variant C. Does not replace
tabular v1, C@8, or Coverage v3.

| Mått | B Jev | C GPT-OSS | Q Qwen Low |
|---|---:|---:|---:|
| Cell accuracy | **0.78** | 0.71 | **0.78** |
| Answer accuracy | 0.81 | 0.74 | **0.82** |
| Citation accuracy | 0.54 | 0.48 | **0.54** |
| Citation grounded | 1.00 | 1.00 | 1.00 |
| ANSWERED cells | 37 | 42 | 35 |
| Seconds/cell p50 | 1.62 | **0.47** | 0.60 |
| USD / 100 cells | unknown | 0.017 | 0.145 |

Qwen Low tied Jev on cell accuracy and beat GPT-OSS.
The gain versus C is fewer false answers on
gold-negative cells (59 vs 51 correct `NOT_FOUND`),
not better gold-positive recall (23/27 for Q, B, and
C). Confidentiality stays the weak question: Qwen
cited the gold unit in 0/20 cells. Six disagreements
with Jev, ten with GPT-OSS. Wall 74s for 100 Qwen
calls.

The 20-document set is still diagnostic. This is not
a default-controller change and not a reason to
touch navigation. A still requested 0 hops.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --cerebras-api-key "$CEREBRAS_API_KEY" \
  --tabular-qwen \
  --output ./data/tabular-qwen-v1.json
```

Frozen as `baselines/phase2-tabular-qwen-v1.json`.

Model comparisons are paused here. Jev B remains the
historical two-step quality baseline. Direct D is the
Tabular performance reference. Qwen Low is not a
quality upgrade. GPT-OSS is faster and cheaper than Qwen
and makes more false answers. Do not test more models
and do not build navigation.

### Tabular citation

Replay of the saved 100 cells. No new model and no new
retrieval. The question is why citation accuracy is
about 54 %: missing gold passages, or wrong source
choice when the passage was already in `k=5`.

| Mått | Värde |
|---|---:|
| Gold-positive cells | 27 |
| Gold hit@3 | 19/27 = 0.70 |
| Gold hit@5 | 20/27 = 0.74 |
| Gold hit@10 | 25/27 = 0.93 |
| Jev source selection when gold in k=5 | **20/20** |
| GPT-OSS source selection when gold in k=5 | **20/20** |
| Qwen source selection when gold in k=5 | 19/20 |
| Missing gold at k=5 | 7, all confidentiality |
| Of those, in top-10 | 5 |
| Still missing at k=10 | 2 |

Jev citation accuracy 0.54 among `ANSWERED` is not a
source-selection failure. When the gold unit is in the
five shown candidates, Jev cites it. Of Jev's 17
`ANSWERED` cells without a gold citation, 14 are
gold-negative false answers and 3 are gold-positive
cells where retrieval never showed the unit. The one
confidentiality gold that reached `k=5` is
`Avtal_06`; Jev cited it, Qwen cited another unit.

Next is document-local retrieval, especially
confidentiality. Not another model. Not navigation.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --tabular-citation \
  --output ./data/tabular-citation-v1.json
```

Frozen as `baselines/phase2-tabular-citation-v1.json`.

### Tabular k=10

Same 100 diagnostic cells. Jev B only. `k=10`
instead of `k=5`. No new model and no navigation.
Default `k` stays 5.

| Mått | B k=5 | K k=10 |
|---|---:|---:|
| Cell accuracy | **0.78** | 0.73 |
| Answer accuracy | **0.81** | 0.75 |
| Citation accuracy | **0.54** | 0.49 |
| True answers | 20 | **24** |
| False answers | **17** | 25 |
| Confidentiality gold cited | 1 | **5** |
| New gold-neg false answers | — | 9 |
| Seconds/cell p50 | **1.62** | 3.09 |

Five of the seven missing confidentiality golds
reach `k=10`. Jev recovered four of those as
`true_answer`. The fifth, `Avtal_13`, was shown
and still cited wrong. Two documents still miss
the gold at `k=10`: `Avtal_01` and `Avtal_22`.

The extra five candidates also created nine new
gold-negative false answers. Net cell accuracy
fell. Source selection when gold is present is
24/25, no longer 20/20. 1 100 Jev calls. Wall
319s. Jev USD unknown.

`k=10` is not the default. It proves that more
candidates can recover confidentiality and still
hurt the table. Document-local ranking still
matters, but the next isolated experiment is
whether the unused classify step is needed at
all.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-k10 \
  --output ./data/tabular-k10-v1.json
```

Frozen as `baselines/phase2-tabular-k10-v1.json`.

### Tabular k=10 errors

Replay of the nine new gold-negative false
answers. No new model. Variant B classifies every
seed, then ignores those votes. `ANSWERED` comes
from a second Jev call that sees every examined
unit. One classify YES is not `ANSWERED`.

All nine cited a rank 6–10 unit. The hybrid top-5
was unchanged. Four are gold-narrow nearby
formulations (`tills vidare`, addendum notice, a
tystnadsplikt gold lists on other employment
contracts). Five are the wrong legal relation
(vite, settlement release, document storage,
driftavbrott disclaimer).

Do not widen `k`. Do not change the Jev prompt.
Do not start a new embedding. Do not build a
thicker controller. Default `k` stays 5.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --tabular-k10-errors \
  --output ./data/tabular-k10-errors-v1.json
```

Frozen as `baselines/phase2-tabular-k10-errors-v1.json`.

### Tabular direct answer

Hypothesis A only. Same frozen B `k=5` keys,
same 100 diagnostic cells, same gold-map v2.
One `answer_cell` after retrieval. Classify is
skipped. Judgments are not passed into the
answer. No navigation. Default B and default
`k` stay 5. Direct D is the experimental
performance reference. Two-step B is the
historical baseline.

| Mått | B tvåsteg | D `answer_cell` | Förbättring |
|---|---:|---:|---:|
| Cell accuracy | 0.78 | **0.78** | Oförändrad |
| Answer accuracy | 0.81 | **0.81** | Oförändrad |
| Citation accuracy | 0.54 | **0.54** | Oförändrad |
| Jev-anrop | 600 | **100** | −83 % |
| Seconds/cell p50 | 1.62 | **0.29** | 5,6× |
| Wall | ~166s | **31s** | 5,4× |

Quality held. Status agreed on 97/100 cells.
One gold-negative false answer became
`NOT_FOUND`. One correct `NOT_FOUND` became
`UNCERTAIN`. One abstention became a false
answer. Net cell score unchanged.

The path is now document-local top-5, one Jev
`answer_cell`, one source-grounded cell. Do not
feed classify into the answer. Do not change
the default runner until D is measured on more
documents. Do not promise local Jev latency.
78 % cell accuracy and 54 % citation accuracy
are not enough. Next is the right five
TextUnits, not more model steps and not a
wider `k`.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-direct \
  --output ./data/tabular-direct-v1.json
```

Frozen as `baselines/phase2-tabular-direct-v1.json`.

### Tabular retrieval signals

Same 100 diagnostic cells. Same document-local
TextUnits. Dense, sparse, and hybrid lists. No
new algorithm and no `answer_cell`. Hybrid
matched the frozen B keys on 100/100 cells.

| Strategi | Gold hit@5 | Gold hit@10 |
|---|---:|---:|
| Dense | **27/27** | **27/27** |
| Sparse | 18/27 | 19/27 |
| Hybrid | 20/27 | 25/27 |

The seven hybrid misses at `k=5` are all
confidentiality. Dense recovers all seven
(ranks 1 or 3). Sparse ranks them 16–32.
Hybrid default stays. Dense top-5 differs
from hybrid on all 100 cells, including the
73 gold-negative ones. Better recall is not
a cell score. `answer_cell` on those dense lists is
measured separately. Hybrid stays the default.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --openai-api-key "$OPENAI_API_KEY" \
  --tabular-signals \
  --output ./data/tabular-signals-v1.json
```

Frozen as `baselines/phase2-tabular-signals-v1.json`.

### Tabular dense answer

Variant D on the frozen dense top-5. Same 100
diagnostic cells. One Jev `answer_cell`. No
navigation. Hybrid D stays the performance
reference.

| Mått | D hybrid | E dense |
|---|---:|---:|
| Cell accuracy | **0.78** | 0.74 |
| Answer accuracy | **0.81** | 0.75 |
| Citation accuracy | **0.54** | 0.52 |
| True answers | 20 | **26** |
| False answers | **17** | 24 |
| Confidentiality recovered | — | **6/7** |
| New gold-neg false answers | — | 10 |
| Jev-anrop | 100 | 100 |
| Seconds/cell p50 | 0.29 | 0.28 |

Dense put gold in every top-5 and recovered six
confidentiality cells. `Avtal_13` still cited
wrong. Ten new gold-negative false answers
outweighed the gain. Net cell −4pp. Same
conflict as `k=10`: better gold coverage is
not a better table. Hybrid stays the retrieval
baseline. 27/27 is diagnostic recall, not
general document understanding.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-dense \
  --output ./data/tabular-dense-v1.json
```

Frozen as `baselines/phase2-tabular-dense-v1.json`.

### Tabular dense errors

Replay of D versus E. No new model. Hybrid D
stays the baseline. No prompt change.

| Övergång | Antal |
|---|---:|
| Tidigare fel → nu korrekt | 7 |
| Tidigare korrekt → nu fel | 10 |
| Tidigare UNCERTAIN → fel | 0 |
| Tidigare fel → annat fel | 0 |
| Tidigare korrekt → UNCERTAIN | 1 |
| Oförändrad | 82 |

Nine of the ten new false answers cited a
TextUnit that hybrid top-5 did not contain.
Seven of those ten are the same cells as the
k=10 false positives. Three are gold-narrow
nearby formulations. Seven are the wrong
legal relation (vite, settlement, driftavbrott,
addendum or main-contract cancellation).

`Avtal_09` liability-cap is the exception: the
cited vite was already in hybrid top-5 and D
said `NOT_FOUND`. `Avtal_13` confidentiality
cited the same settlement-secrecy clause as
D. Gold, the ongoing trade-secret duty, was
dense rank 3.

Do not change the Jev prompt from this
replay. Do not change default hybrid.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --tabular-dense-errors \
  --output ./data/tabular-dense-errors-v1.json
```

Frozen as `baselines/phase2-tabular-dense-errors-v1.json`.

### Tabular answer_cell prompt-dev

P0 versus three isolated instructions. Same
architecture: OverGraph → five TextUnits → one
Jev `answer_cell`. Hybrid D stays the
performance reference. Both hybrid and dense
lists were used. The ten known false answers
were diagnostic only, not the selection gold.

Selection set: five stable true cells and five
stable correct negatives, both lists. 20 cells
per prompt. All four prompts scored 10 true
answers, 0 false answers, citation 1.0, 0
`UNCERTAIN`. P0 remains.

| Mått | P0 | P1 | P2 | P3 |
|---|---:|---:|---:|---:|
| Selection cell | **1.00** | 1.00 | 1.00 | 1.00 |
| Selection true answers | **10** | 10 | 10 | 10 |
| Selection false answers | **0** | 0 | 0 | 0 |
| Error-set false answers | 12 | 11 | 11 | 11 |
| `UNCERTAIN` | 0 | 0 | 0 | 0 |
| Jev-anrop | 42 | 42 | 42 | 42 |
| Tokens in/out | 253k/62k | 254k/62k | 254k/62k | 254k/62k |
| Seconds/cell p50 | 0.29 | 0.29 | 0.29 | 0.28 |

The only change versus P0 was Avtal 09
liability-cap on the dense list: P1–P3 said
`NOT_FOUND` where P0 accepted the vite clause.
Avtal 13 confidentiality still cited
settlement secrecy on every prompt and both
lists. Nine of the ten known dense false
answers were unchanged.

A one-cell diagnostic win on a known error is
not a quality result. No holdout. Default
`answer_cell` stays P0. Default hybrid stays.
Do not write more term-specific rules.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-prompt-dev \
  --output ./data/tabular-prompt-dev-v1.json
```

Frozen as `baselines/phase2-tabular-prompt-dev-v1.json`.

### Tabular English questions

P1–P3 were already English. This run keeps the
frozen P0 instruction and changes only the
question language. Same 21-cell development
set. Both lists. Swedish P0 stays the
reference.

| Mått | P0 Swedish | P0 English |
|---|---:|---:|
| Selection cell | **1.00** | 1.00 |
| Selection true answers | **10** | 10 |
| Selection false answers | **0** | 0 |
| Error-set false answers | **12** | 14 |
| `UNCERTAIN` | 0 | 0 |
| Jev-anrop | 42 | 42 |
| Seconds/cell p50 | 0.29 | 0.29 |

English did not lose a true positive. It added
two hybrid false answers: Avtal 09
liability-cap (vite) and Avtal 36
notice-period (termination for breach). Avtal
13 still cited settlement secrecy. Swedish
questions stay. No holdout. Default P0 stays.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-prompt-en \
  --output ./data/tabular-prompt-en-v1.json
```

Frozen as `baselines/phase2-tabular-prompt-en-v1.json`.

### Tabular status P0_v2

New status definitions, then a decision tree, then
sharper questions with "Räknas inte" on every
question. Nearby topical units are gold
`UNCERTAIN`. False `ANSWERED` is the costlier
error. Default P0 stays.

| Steg | True ANSWERED | False ANSWERED | Missade svar |
|---|---:|---:|---:|
| A P0 | 10 | 7 | 0 |
| B definitioner | 10 | 4 | 0 |
| C beslutsträd | 10 | 4 | 0 |
| D skarpare frågor | **11** | **0** | 0 |
| E engelska D | 11 | 1 | 0 |

D met the acceptance bar: Avtal 09 and 17 had
zero false `ANSWERED` on 5/5 repeats. Avtal 13
dense cited 6.1 in 5/5 permutations. No true
`ANSWERED` was lost. Avtal 13 hybrid still
lacks 6.1; that is a retrieval miss.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-status-v2 \
  --output ./data/tabular-status-v2.json
```

Frozen as `baselines/phase2-tabular-status-v2.json`.
Table: `eval/status-v2.md`.

### Tabular status P0_v2_D repeats and holdout

Jev has no temperature. D was repeated five times on
the 23 prompt-scored cells, then on five unseen
near-misses whose wording is not a named exclusion.

| Mängd | True ANSWERED | False ANSWERED | Spridning |
|---|---:|---:|---|
| 23 prompt-scored | 11 / 11 / 11 | 0 / 0 / 0 | none |
| Unseen holdout | 0 | 1 | none |

Eleven true answers is stable, not a small-n fluke.
The unused HARD_NEG in status-v2 are in-distribution
for named `Räknas inte` exclusions (vite, tills
vidare, avtalets innehåll, hävning). They do not
show generalization.

Unseen holdout: Avtal 35, 20, 76 and 52 stayed
`UNCERTAIN`. Avtal 92 (förlikning, "inga ytterligare
krav") was false `ANSWERED` in 5/5. D did not
generalize. Default P0 stays.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-status-v2-repeats \
  --output ./data/tabular-status-v2-repeats.json
```

Frozen as `baselines/phase2-tabular-status-v2-repeats.json`.
Table: `eval/status-v2-repeats.md`.

### Tabular Jev probability P1

Jev already returns `confidence` for the chosen
alternative and `probabilities` for every listed
choice. `answer_cell` had been discarding both.
P1 collected them on the same 100 cells, same
hybrid top-5, same P0 prompt, one call per cell.
Status was not changed by the score.

| ANSWERED | n | min | median | mean | max |
|---|---:|---:|---:|---:|---:|
| True | 20 | 0.33 | 0.99 | 0.90 | 1.00 |
| False | 17 | 0.18 | 0.94 | 0.77 | 1.00 |

False answers are a bit lower on average. The
ranges overlap. True answers go down to 0.33;
false answers include several 1.0, among them
Avtal 13 citing settlement secrecy. Explicit
`UNCERTAIN` appeared once. P2 was not implemented.
Rejected as a status signal. Keep explicit
`UNCERTAIN`. Keep the raw score fields for
diagnostics. No threshold, no new controller.
Default P0 stays. The 100-cell parameter
sweeps have plateaued; next is whether the
five user questions ask the same thing as gold.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --gold-dir ./retrieval_gold \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-probability \
  --output ./data/tabular-jev-probability-v1.json
```

Frozen as `baselines/phase2-tabular-jev-probability-v1.json`.
Table: `eval/probability-v1.md`.

### User questions versus gold

Jev sees the Swedish user question. Gold was
written for retrieval inventory and classify.
Fourteen of seventeen P1 false `ANSWERED` are
gold-negative. Two of those are operative NDA
clauses missing from confidentiality gold
(Avtal 07, Avtal 30). Carve-out is the only
question where user, classify, and notes ask
for the same relation.

Gold and user questions are unchanged. Do not
retune gold to the model. Frozen as
`baselines/phase2-tabular-question-gold-v1.json`.
Table: `eval/question-gold-v1.md`.

78 % cell accuracy and 54 % citation accuracy
stay as passage-gold history. They are not
Tabular Review quality against the question
the user asked.

### Tabular Review user gold

The user question is the contract. A separate
100-cell gold was read from the twenty
documents, without looking at Jev answers and
without editing retrieval gold. One document
may have several acceptable spans. Silence is
not a no unless the whole document was read.

Frozen D, E, and K were rescored offline. No
new prompt. No new model run.

| Variant | Passage gold | User gold |
|---|---:|---:|
| D (hybrid k=5) | 78 % | **84 %** |
| E (dense k=5) | 74 % | **90 %** |
| K (hybrid k=10) | 73 % | **90 %** |

Against passage gold D looked best. Against
the user question E and K do. D still misses
operative secrecy duties that were never in
`relevant_units`. Remaining false answers are
nearby relations: vite as a cap, settlement
as a cap, a heading as a duty, the liability
clause as secrecy.

```bash
uv run overgraph-ingest \
  --tabular-user-gold \
  --output ./data/tabular-user-gold-v1.json
```

Frozen as `baselines/phase2-tabular-user-gold-v1.json`.
Table: `eval/user-gold-v1.md`.

D stays the historical performance reference
and the default (hybrid k=5, one `answer_cell`).
E is the most promising next candidate, not a
default change. Do not add special rules for
vite, settlement, headings, or nearby caps.
Do not keep tuning on the diagnostic twenty.
A cell may list several structured answers.

### Baseline writes are opt-in

Every command below writes its table and
`--output` JSON on a normal run. The `baselines/`
JSONs are only written when `--freeze-baseline`
is passed, and an existing baseline is never
overwritten. Run without the flag to replay or
re-score a command against the committed
baselines.

### Holdout gold before models

Twenty leftover documents, every third unseen
Avtal by number, excluding the diagnostic
twenty and the status-v2 cases. Question gold
was written from the documents. D, E, and K
have not been run.

```bash
uv run overgraph-ingest \
  --tabular-holdout \
  --output ./data/tabular-holdout-gold-v1.json
```

Frozen as `baselines/phase2-tabular-holdout-gold-v1.json`.
Table: `eval/holdout-gold-v1.md`.

### Holdout D/E/K on current ingest

Locked comparison. Current ingest and embeddings.
Unchanged P0. One `answer_cell`. No classify.
No structural preprocess. Default stays D.

| Variant | Full success | Positive 43 | Silent stayed 57 | False on silent |
|---|---:|---:|---:|---:|
| D hybrid k=5 | 79% | **27** | **52** | **5** |
| E dense k=5 | **89%** | **39** | 50 | 6 |
| K hybrid k=10 | 87% | 35 | **52** | **4** |

E found 12 more addressed cells than D and added
one silent false answer. K sits between them.
Do not pay for ten hybrid candidates. Do not
switch the default from this table alone.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-holdout-run \
  --output ./data/tabular-holdout-run-v1.json
```

Frozen as `baselines/phase2-tabular-holdout-run-v1.json`.
Table: `eval/holdout-run-v1.md`.

### Structure-aware TextUnit embeddings

Hypothesis 1: embed a TextUnit with its stored
document structure. Search text is not evidence.
No Jev. No legal parser. Start with A vs B.
C and Jev-at-ingest wait.

The spent holdout plus the diagnostic twenty
are development material. A new reserved
twenty is unused.

A and B tied at hit@5 (81/84). B raised MRR
and hit@10, lowered hit@3, and doubled embedding
tokens. **B is rejected.** Original embeddings stay.
Do not run C. Next was candidate presentation:
the same five units, with stored headings in
`answer_cell`. Default stays D.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --tabular-enrich \
  --output ./data/tabular-enrich-v1.json
```

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --tabular-enrich-run \
  --output ./data/tabular-enrich-run-v1.json
```

B rejected: `baselines/phase2-tabular-enrich-reject-v1.json`.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --tabular-present \
  --output ./data/tabular-present-v1.json
```

Frozen as `baselines/phase2-tabular-present-v1.json`.
Table: `eval/present-v1.md`.

### Candidate presentation to Jev

One isolated variable: stored clause number and
heading path on the same dense k=5 TextUnits.
P0. One `answer_cell`. Original evidence text.
No new ingest, embeddings, retrieval, or prompt.
Reserved holdout unused.

TEXT 89.5% (85/94 positive, 94/106 silent, 12
false on silent). PRESENT 88% (84/94, 92/106,
12 false). Eight cells changed despite identical
candidates. One previously correct positive was
lost. False positives did not fall. Jev did not
cite heading metadata as evidence.

**Do not add more metadata fields.** Do not run
the reserved holdout. Default stays D.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-present-run \
  --output ./data/tabular-present-run-v1.json
```

Frozen as `baselines/phase2-tabular-present-run-v1.json`.
Table: `eval/present-run-v1.md`.

**PRESENT is rejected.** Text-only `answer_cell`
stays. Headings in embeddings and headings in
Jev context both failed, at different layers.
Do not compare the development 89.5% with the
separate Dense k=5 holdout 89%. Default stays
D. Dense k=5 remains the strongest measured
candidate. Pause micro-optimization of the
same five TextUnits. Do not start ingest
labeling because the cheaper representations
failed. Next quality needs a new capability.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --tabular-present-reject \
  --output ./data/tabular-present-reject-v1.json
```

Frozen as `baselines/phase2-tabular-present-reject-v1.json`.
Table: `eval/present-reject-v1.md`.

### Multiple answers per cell

Last isolated quality experiment before a
product table. Same dense k=5 TextUnits. One
Jev call. Single keeps P0. Multi lists distinct
listed excerpts. Documents are the 24 with
several gold answers. Reserved holdout unused.

On those 31 multi-span cells SINGLE found 32/65
gold answers with 0 extras. MULTI found 46/65
and added 4 extras. Thirteen cells gained gold
with no new extras. Eight cells added extras.

Jev can return several cited answers in one
call. That is not an unfiltered quality win.
Default stays D. Do not start the Socialism
table from this run.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --openai-api-key "$OPENAI_API_KEY" \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --tabular-multi-run \
  --output ./data/tabular-multi-run-v1.json
```

Frozen as `baselines/phase2-tabular-multi-run-v1.json`.
Table: `eval/multi-run-v1.md`.

### Document classification at ingest

A new reusable document property, not better
embeddings and not more clause metadata.
Classify each document once so Socialism can
ask for all employment agreements without
re-analysing them. Experiment only.

Gold is locked first. Principal function, not
clauses. A consulting agreement with secrecy
is not an NDA.

A uses title, opening, headings, and stored
metadata. B is one Jev choice on that view.
C adds a fixed extra-text budget. No graph
navigation. Type is stored on Document.
TextUnits stay unchanged.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --doctype-gold \
  --output ./data/doctype-gold-v1.json
```

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --doctype-run \
  --output ./data/doctype-run-v1.json
```

Gold: `baselines/phase2-doctype-gold-v1.json`.
Table: `eval/doctype-gold-v1.md`.

| Variant | Accuracy | Jev calls/doc | Latency ms/doc |
|---|---:|---:|---:|
| A structure | 81% | 0 | 0 |
| B Jev on A view | **86%** | 1 | 272 |
| C Jev plus extra text | 84% | 1 | 277 |

Jev added 5 points over structure-only A.
Wider context did not help: C lost two
documents that B had. Remaining B errors
are mostly adjacent commercial documents
called supply. Hard cases stayed distinct
except the subcontract (36), which B/C
called supply.

200 Jev calls. 55s wall. OverGraph filter
2.7 ms. Phase 2 TextUnits unchanged.
No production ingest.

Frozen as `baselines/phase2-doctype-run-v1.json`.
Table: `eval/doctype-run-v1.md`.

### Document tags and stored classification

Next isolated experiment after document
classification. Store the frozen B type,
Jev confidence, probabilities, tag classes,
automatic tags, user corrections, and
validated excerpts. Experiment only.

Gold is locked first on 16 contracts.
A is deterministic extraction. B is one
Jev call on the frozen type plus relevant
text. User corrections survive re-ingest.
No approval threshold. Not legal proof.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --document-tags-gold \
  --output ./data/document-tags-gold-v1.json
```

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --dense-dimension 3072 \
  --typesafe-api-key "$TYPESAFE_API_KEY" \
  --document-tags-run \
  --output ./data/document-tags-v1.json
```

Gold: `baselines/phase2-document-tags-gold-v1.json`.
Table: `eval/document-tags-gold-v1.md`.

| Variant | Precision | Recall | Hits | Extras | Misses | Jev/doc | Latency ms/doc |
|---|---:|---:|---:|---:|---:|---:|---:|
| A structure | 86.5% | 94.1% | 32 | 5 | 2 | 0 | 0 |
| B Jev on frozen type | 91.4% | 94.1% | 32 | 3 | 2 | 1 | 384 |

Same 32/34 hits. B had fewer extras. A had
validated sources on every hit. B left 10 hits
unvalidated. 16 Jev calls. 6.4s wall. Filter
2.0 ms. User type/tag corrections survived
re-ingest. Tenant isolation held. Phase 2
TextUnits unchanged. No production ingest.

Frozen as `baselines/phase2-document-tags-v1.json`.
Table: `eval/document-tags-v1.md`.

A is the cheap ingest candidate. B is an
experimental alternative for more semantic
classes. Automatic tags stay proposals.

Lifecycle review, no Jev:

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --document-tags-lifecycle \
  --output ./data/document-tags-lifecycle-v1.json
```

Frozen as `baselines/phase2-document-tags-lifecycle-v1.json`.
Table: `eval/document-tags-lifecycle-v1.md`.

The tag experiment is closed. No more Jev on
the 16 documents. Carry the data model into
`docs/specs/document-catalog-integration.md`.
Do not import this package into Socialism.

```bash
uv run overgraph-ingest \
  --db ./data/extra-overgraph-phase2 \
  --document-tags-close \
  --output ./data/document-tags-close-v1.json
```

Frozen as `baselines/phase2-document-tags-close-v1.json`.
Table: `eval/document-tags-close-v1.md`.

## Tests

```bash
uv run pytest
```
