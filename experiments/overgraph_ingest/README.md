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

## Tests

```bash
uv run pytest
```
