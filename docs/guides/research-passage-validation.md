# Truncated preparatory works: local validation

Date: 2026-09-23. Local branch: `codex/research-quality-speed`.

## Change

A named citation can resolve to the correct document while the MCP's 200,000-character root response excludes the relevant later material. A truncated preparatory-work response now triggers up to three short, LLM-planned searches scoped by document number. Only fragments whose document identity matches the fetched source are eligible. Their actual text is retrieved before the legal interpreter judges relevance. Root and fragment fetches share the existing five-document and twelve-tool-call bounds.

The search snippet selector is deliberately not used again for these verified fragments. In a live probe it rejected `prop/1975/76:81#a10-2` because the snippet discussed credit, although the full fragment contained discussion of weaker parties and arbitration clauses. Search highlights often emphasize the document number rather than the substantive search term.

Empty passage results produce `passage_not_found`; the truncated root prefix is not silently treated as the complete source. A mismatched document or pinpoint in the fetch response is rejected. Prompts are configurable through the existing prompt store; migration 115 registers the two new keys.

## Evidence

Public test question: “Vad säger specialmotiveringen till 36 § avtalslagen i prop. 1975/76:81 om skyddet för svagare avtalsparter?”

- Initial phrase searches returned no usable fragments in 9.74 seconds.
- Single substantive terms with a quoted document number located same-document fragments. A retrieval-only probe took 4.44 seconds, before the final shared document-budget adjustment. This timing excludes legal interpretation.
- The full local provider, using the existing run's customer/module configuration, took 19.43 seconds and returned four grounded results, including the previously excluded late fragment `#a10-2`. It used one citation resolution, three searches and five document fetches including the root. No stored research attempt was mutated.
- These are individual probes, not latency distributions or an end-to-end research benchmark.

## Remaining quality issue

The full probe exposed incorrect attribution in the legal interpreter: it called remissinstanser material (`#a4.2.1`, `#a4-2`) and proposed statutory wording (`#a36`) “specialmotivering” and marked them as direct support. Exact quote grounding therefore does not establish correct author, text role or requested section. The passage retrieval change does not fix this. Before treating the original question as answered, add source-role-aware preparatory-work interpretation and regression cases that distinguish government commentary, consultation responses, proposed wording and committee material.

Also measure recall across more long documents and end-to-end latency with interpretation enabled. The search result cap can still omit the exact requested section. Jev remains in shadow mode; one successful replay is not sufficient calibration for automatic sufficiency decisions.


## Attribution iteration

The initial attribution prompt and structured fields alone did not fix the live false positives: the model selected a source role to fit the question. The interpreter now first classifies the source opening without receiving the research question. It reads at most 16,000 characters in complete source paragraphs and supplies grounded speaker/role citations. The main interpretation cannot overwrite that source attribution. If a proposed `supports` relation conflicts with the requested text role or the role is unknown/contents, it becomes `contextual`, with low confidence, an explicit explanation, an unresolved requested-role question and an analysis limitation. The correction is transparent and does not trigger repeated model calls. Missing or fabricated attribution spans still fail validation.

Attribution is retained in stored analyses, expert summaries and structured claims, including the attribution's own supporting citations. Interpretation schema version 5 prevents reuse of older analyses through both provider cache and Question→Evidence lookup. Existing historical records remain readable; they are not treated as freshly validated answers. Migration 116 registers the classification and attribution prompts without changing existing customer overrides.

The same full live question took 28.83 seconds after this change: all four returned results were contextual, with no extraction errors or false direct-support labels. The consultation section was correctly identified as consultation material and proposed statutory wording as such. An intermediate version spent 31.56 seconds and lost two passages to repeated validation failures; explicit relation restriction removed those retries. These are single observations, not a performance benchmark.

Remaining: the exact requested special-commentary passage still has not been retrieved and verified. Classification of mixed or mid-section text is imperfect: in this probe one large earlier block was classified as government general reasoning despite containing inquiry/consultation discussion. The role restriction protects the special-commentary question, but a wider speaker-attribution evaluation and more precise passage boundaries are still needed. Do not claim this question is fully answered. The initial 16,000-character source-context bound can leave the role unknown. No broader Jev calibration or complete production research rerun has been performed.
