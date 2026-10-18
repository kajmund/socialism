# Spec: Facit + provenance (facit-builder)

## Goal
Build `ground_truth/facit.json` (one entry per golden question) and
`ground_truth/provenance.json` (fact → document-position register).

## Inputs (read-only)
- `golden_questions/golden_questions.json` (200 questions, no answerability field)
- `ground_truth/coverage_matrix.json` (per-question mapping + answerability)
- `generator/data/answerability.json` (classes)
- `ground_truth/truth_model.json` – load with `Model().load(...)`
- `generator/data/facts.json` – entities/events/key figures/anomalies with computed values
- `generator/compute.py` – CANONICAL CALCULATORS. Use these for every numeric answer:
  C.total_revenue, C.seab_share, C.customer_share, C.cash_at, C.overdraft_at,
  C.open_ar, C.overdue_ar, C.revenue_by_customer, C.revenue_by_month,
  C.balances_at, C.pnl_by_vouchers, C.index_adjusted_rate, C.missed_index_total,
  C.underbilling_total, C.net_result, C.D, C.M, C.pct. Never recompute by hand.
- `generator/data/contracts_manifest.json` + `generator/data/operations_manifest.json`
  (document registry with doc_ids, paths, entities) – your source references must
  point at these doc_ids/paths.
- The generated documents themselves (contracts/*.docx, management/*.docx, ...) for
  exact quote/position verification. Use python-docx to read paragraphs/tables when
  you need to cite a section number or clause.

## Output 1: ground_truth/facit.json
Array of 200 entries (GQ order):
{
 "question_id": "GQ-001",
 "answerability": "<class>",
 "expected_answer": {
    "type": "number|list|text|mixed|none",
    "value": <the expected answer, e.g. "207 842,04 kr på företagskontot; disponibel checkkredit 580 000 kr">,
    "numeric": <single number when applicable, else null>,
    "tolerance_pct": <e.g. 0.5 for money questions, null for text>
 },
 "method": "<beräkningsmetod eller resonemangsregler, steg för steg>",
 "required_info": ["<krävd information>", ...],
 "sources": [{"doc_id": "DOC-...", "path": "management/....docx", "position": "§7, stycke 2 / rad 12 / tabell cell", "valid_from": "...", "valid_to": "..."}],
 "computations": [{"formula": "...", "inputs": {...}, "result": "..."}],
 "entities": ["CUS-001", ...],
 "capabilities_tested": ["..."],
 "rubric": {"full_credit": "...", "partial": "...", "zero": "..."},
 "external_facts": ["KPI SCB", ...],
 "answered": true/false   (true unless INSUFFICIENT_EVIDENCE)
}
- For INSUFFICIENT_EVIDENCE: expected_answer.type="none", value=null, answered=false,
  method explains exactly which datum is missing and what a complete answer would require.
- For CONFLICTING_EVIDENCE: expected_answer describes BOTH readings + the
  qualification a correct answer must make (e.g. "enligt HR-rapporten 9, enligt
  lönelistan 10; korrekt svar kvalificerar källan och anger orsaken").
- For EXTERNAL_DEPENDENCY: expected_answer references the external source
  (with the embedded snapshot where available, e.g. KPI-serien i config) and states
  which part is externally dependent; answered=true when the embedded snapshot
  suffices for the computation, else answered=false with the needed external fact.
- Numeric answers computed via compute.py + rounded to whole SEK unless the question
  implies decimals; set tolerance_pct 0.5 for computed money, 5 for judgment answers.
- For questions about "belopp just nu / per 2026-10-18": use the 2026-09-30
  bookkeeping (senaste tillgängliga data) and SAY SO in method.

### Answers to anchor on (computed, do not re-derive)
- Bank at end: C.cash_at(postings, "2026-09-30"); checkkredit disponibelt =
  3 000 000 − C.overdraft_at(...) (drawn is 0 at end).
- GQ-002 runway: monthly fixed costs ≈ 3.2 MSEK (personnel 2.7 + external 0.5);
  with −20 % revenue the monthly deficit ≈ 0.7 MSEK → runway =
  (cash + available OD) / 0.7 MSEK. Document assumptions explicitly.
- GQ-042/182/193 SEAB dependency: C.seab_share FY2026 ≈ 34.4 %; SEAB revenue FY2026 ≈
  C.revenue_by_customer(...)["CUS-001"]; notice periods from contracts CTR-2023-002/
  CTR-2024-010/CTR-2026-002 (ramavtal 3 mån, SE-Billing löper ut, SE-Förvaltning
  auto-renew 12 mån med 3 mån uppsägning).
- GQ-053 missed index: GV correct rate 1 075 kr/h (C.index_adjusted_rate(1050,"2023-10","2025-10")),
  missed net C.missed_index_total(SCH-004,...); BV 1 009 kr/h, C.missed_index_total(SCH-010,...).
- GQ-052: KF index applied 2025-11-01 (1 150) but billed late; GV/BV never applied.
- GQ-004 overdue: C.overdue_ar() (Blåklintens Vård + Stormvindens Logistik + Örby-tvisten 96 800).
- Bad debt: 220 065,00 kr (Sjöstadens Bryggeri, sep- + nov-fakturorna; sep hölls inne
  p.g.a. reklamation, okt betalades sent 2025-11-20). TS kreditnota 90 000 kr inkl. moms.
  Örby-tvisten: 96 800 kr inkl. moms.
- GQ-091 auto-renewal within 90 days: CTR-2025-014 (FS-Förvaltning), CTR-2022-028 (KP),
  CTR-2025-013 (NE), CTR-SUP-006 (Kanalen), CTR-SUP-007 (Designsuiten), CTR-SUP-012
  (Modellfabriken) + CTR-2023-018 (BV) om ej uppsagt (beslut skjutet 2026-09-15).
- GQ-092: CTR-2024-016 (obegränsat ansvar), CTR-2023-015 (24 mån funktionsgaranti),
  CTR-2025-011 (vite 1 %/vecka tak 10 %), CTR-2026-001 (vite + källkodsdepå).
- GQ-096: CTR-2023-002 (SEAB exklusivitet), CTR-2025-007 (Polstjärnan).
- GQ-097: CTR-2023-002, CTR-2025-007, CTR-AKT-001 (change_of_control).
- GQ-099: top-10 by FY26 revenue → their notice_months from contracts.
- GQ-102: employees hired before 2023-02-15 whose contract lacks the new
  sekretessbilaga (derive from CTR-EMP-* records' risk_flags GAMMAL_SEKRETESS).
- GQ-108: konkurrensklausuler i CTR-EMP-32 (Gustav), CTR-EMP-36 (Rasmus) + gamla mallen.
- GQ-112: DPAs with risk flag GAMMAL_DPA_MALL.
- GQ-117: SUP-013 Analytics Cloud Inc (USA, SCC).
- GQ-119: gallringsfrister i policyn + bokföringslagen (7 år) — external.
- GQ-150: utdelningsutrymme = fritt eget kapital vid 2026-09-30 (compute from balances:
  2091 + 2099-ish; note the FY26 tax payable and the aktieägaravtalets regler).
- GQ-157 beläggning: from projects/tidrapporter.csv (debiterbara timmar /
  tillgängliga timmar per team).
- GQ-177: cloud spend per month = Σ streams STR-004..STR-023 (5420) per month.
- GQ-161: top-5 suppliers by FY26 spend (Kapellbacken 2 131 000, Pensionsvalet
  1 771 952, Kraftkod 1 360 000, Cloudserve 1 147 000, Dataverket 764 400).
- GQ-198: budget 47.0 MSEK vs ledningsrapport/utfall 54.3 MSEK vs pipeline 10.8–13.1 MSEK.

## Output 2: ground_truth/provenance.json
Register linking facts to document positions:
[
 {"fact_id": "F-001", "fact": "<påstående>", "entities": [...],
  "sources": [{"doc_id": "...", "path": "...", "position": "...", "quote": "..."}],
  "derived_from": ["<fact_id or 'truth_model'>"], "valid_from": "...", "valid_to": "..."}
]
Cover at least: all key figures, all anomalies (§2.4 i README), contract risk clauses,
top suppliers, SEAB share, all computed index/catch-up amounts, OD peak, bad debt,
tvist, covenant, budget vs actuals, pipeline totals. Aim ≥80 facts.

## Rules
- Use compute.py for ALL numeric answers (the validator recomputes and must match).
- Source paths must exist in the tree (contracts/, management/, ...). Verify with
  Path.exists(); if a referenced doc is missing, drop it from sources and note it.
- Do not modify anything outside ground_truth/facit.json and ground_truth/provenance.json.
- Report back: entries written, how many questions are fully answered vs partial, any
  question you could not produce a grounded answer for (and why), and any missing
  referenced documents you discovered.
