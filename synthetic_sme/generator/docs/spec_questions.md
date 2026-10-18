# Spec: Golden Questions + coverage matrix (qa-author)

## Goal
1. `golden_questions/golden_questions.json` – the 200 questions, preserving the
   ORIGINAL ids and wording from the source workbook.
2. `ground_truth/coverage_matrix.json` – per-question data/capability mapping.

## Inputs
- `generator/data/golden_questions_raw.json` – 200 rows from the workbook
  (ID, Område, Delområde, Golden question, Förväntat underlag, Databehov, Förmåga,
  Svårighetsgrad).
- `generator/data/facts.json` – all entities, events, anomalies, key figures.
- `generator/data/answerability.json` – the lead's classification
  (ANSWERABLE / PARTIALLY_ANSWERABLE / INSUFFICIENT_EVIDENCE /
  CONFLICTING_EVIDENCE / EXTERNAL_DEPENDENCY) per question id. Do not change it;
  embed it into the coverage matrix.

## Output 1: golden_questions.json
Schema (array of 200, in GQ order):
{
 "id": "GQ-001",
 "area": "Ekonomi",
 "subarea": "Likviditet och kassaflöde",
 "question": "<exact original text from the workbook, verbatim>",
 "capability": "<Förmåga from workbook>",
 "difficulty": "<Svårighetsgrad from workbook>",
 "expected_underlag": "<Förväntat underlag from workbook>",
 "databehov": "<Databehov from workbook>",
 "answerability": "<class from answerability.json>"
}
Keep original formulations EXACTLY (do not fix typos or reformulate).

## Output 2: coverage_matrix.json
Array of 200 entries:
{
 "id": "GQ-001",
 "answerability": "...",
 "requires_data": ["accounting/banking/bankkontoutdrag.csv", "ground_truth? NO –
   use ingest-side paths only"],
 "required_entities": ["CUS-001", ...] (ids from facts.json where applicable),
 "multi_source": true/false  (true when >= 2 independent files are needed),
 "capabilities_tested": ["beräkning", "retrieval", ...],
 "computed_or_reasoned": "computed" | "reasoned" | "hybrid",
 "external_facts": ["KPI", ...] or [],
 "notes": "short note on what the question exercises"
}
- "requires_data" must reference files that exist in the synthetic_sme tree
  (accounting/**, management/**, policies/**, correspondence/**, employees/**,
  customers/**, suppliers/**, projects/**, contracts/**, invoices/**,
  golden_questions/**). Do NOT reference ground_truth files (the system under
  test never sees them).
- ≥30 % of the 200 must have multi_source=true (aim ~60+ questions).
- For INSUFFICIENT_EVIDENCE questions: requires_data lists the closest available
  files and notes WHY they are insufficient (what specific datum is missing).
- For CONFLICTING_EVIDENCE: notes which files conflict on what.
- For EXTERNAL_DEPENDENCY: external_facts lists the needed external source
  (e.g. "ABL 25 kap.", "KPI SCB", "marknadsprisdata konsulttjänster 2026").

## Rules
- Write ONLY the two files above. No other files.
- Use facts.json entities (customers CUS-xxx, persons P-xxx, projects PRJ-xxx,
  contracts CTR-xxx) when naming required entities.
- Report back: counts per answerability class, multi_source count, any question
  whose original text seemed truncated in the workbook.
