# Legal ResearchNeed validation

The generic research engine does not know Swedish legal tracks. Before retrieval, the legal domain validates ResearchNeeds that target `swedish_law`, `swedish_case_law`, or `swedish_preparatory_works`.

```text
ResearchNeed generated
  → legal question validator (LLM + structured output)
      keep | rewrite | split
  → persist runtime needs / DAG
  → retrieval
```

The validator does not search. It judges institution, provision, remedy, field of law, and consumer vs commercial track. Mixed tracks are split; coherent questions stay unchanged. Normalized needs are marked `already_normalized` so they are not rewritten again.

Unfair contract terms are two tracks:

- Market law: MD / PMD / KO and 3 § AVLK
- Civil law: general courts and 36 § AvtL (AVLK consumer rules may apply there, but they do not make MD/KO into 36 § courts)

Production wires this through `LegalResearchPlannerAdapter` / `LegalFollowUpPlannerAdapter` in `bind_research_components`. Tests inject `LegalNeedNormalizer`.
