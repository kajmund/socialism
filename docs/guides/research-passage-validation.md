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
