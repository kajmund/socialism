# Spec: Contract document generation (docs-contracts)

## Goal
1. Add ≥25 supplementary contract RECORDS so the total is ≥200 (current: 182 in the
   truth model), saved to `generator/data/contracts_supplement.json`.
2. Render EVERY contract record (truth model + supplement) as a DOCX in
   `contracts/{customers,suppliers,employees,corporate}/` with varied, realistic
   Swedish legal structure (not identical templates).
3. Write `generator/data/contracts_manifest.json` with provenance entries.

## Inputs (read-only)
- `ground_truth/truth_model.json` – canonical model. Read with:
  `from generator.model import Model; m = Model().load("ground_truth/truth_model.json")`.
  Fields of contract records: id, kind, title, counterparty_type, counterparty_id,
  counterparty_extra, signed, effective_from, expires, auto_renew_months,
  notice_months, payment_days, pricing_model, rate, amount, index (dict),
  liability_cap, exclusivity, change_of_control, versions, status, finance_link,
  project_ids, risk_flags, note.
- `generator/data/facts.json` – entity overview.
- `generator/docgen/common.py` – shared DOCX helpers (new_doc, heading, para, kv,
  table, right, save). Use the bundled python: 
  `/Users/erikfremred/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3`
  (has python-docx). Run from `/Users/erikfremred/socialism/synthetic_sme`.

## Output 1: contracts_supplement.json
Same schema as `contracts` in the truth model. Constraints:
- counterparty ids MUST exist in the model (customers CUS-xxx / suppliers SUP-xxx /
  persons P-xxx for employees / null for corporate).
- `finance_link` must be null and no project_ids that create new revenue/cost.
- ids: CTR-SUPPL-001..0NN (unique, not colliding).
- Include at least: 12 NDA, 8 DPA, 2 LEASING, 2 SAAS, 1 HYRA, 1 KONSULTAVTAL,
  2 AKTIEAGARE/corporate. Some with versions[], some auto_renew, varied dates
  2021-2026. Use util.rng("contracts-supplement") for any randomness.
- Add risk_flags/notes where realistic (e.g. an NDA with icke-konkurrens, a DPA
  based on the old 2021 SCC mall with note "GAMMAL_DPA_MALL").

## Output 2: DOCX files
For EVERY record (182 + supplement). File name: `<id>_<short-slug>.docx`
(e.g. `CTR-2023-002_SE-Billing.docx`). Slug must NOT contain risk words like
"risk", "obegransat", "missad" – use the contract title/party. NO benchmark tags,
no answer markings, no hidden text.

### Faithful clause rendering (critical)
The DOCX MUST contain the clauses that the record encodes. Map:
- `pricing_model TIMPRIS/INDEXTIM` + `rate` → prisklausul with kr/h.
- `index` dict → indexklausul: "Priserna uppräknas årligen per [due-månad] med
  KPI, basmånad [base_month]. Uppräkning sker med faktorn KPI(basmånad−1)/KPI(base)."
  If `applied_in_invoicing` false → clause exists (we just haven't applied it –
  do NOT write anything revealing this).
- `amount` + ABONNEMANG/FAST → fast pris/avgift, ev. milstolpar for PROJEKTAVTAL FAST
  (invent realistic milestone rows matching finance_link if present).
- `auto_renew_months` → "Avtalet förlängs automatiskt med [n] månader om det inte
  sägs upp senast [notice_months] månader före utgången."
- `liability_cap` → ansvarsbegränsningsklausul. If "OBEGRÄNSAT ansvar..." render an
  unlimited-liability clause: "Parts ansvar är inte begränsat..." (this is the
  risky deviation; render it as a normal clause).
- `exclusivity` → exklusivitets-/konkurrensklausul with the given text.
- `change_of_control` true → förändringsklausul: motparten får säga upp avtalet vid
  ägarförändring/kontrollägarskifte.
- `versions` → "Ändringshistorik" section listing version, date, summary.
- ANSTALLNING: lön (amount), befattning, tillsvidare, 6 mån provanställning for
  hires, sekretessbilaga (referens "Sekretessbilaga 2023-02-15" for confidential,
  older bilaga reference otherwise), konkurrensklausul if risk flag
  KONKURRENSKLAUSUL (12 mån/6 mån).
- DPA: referens till mallversion; om GAMMAL_DPA_MALL använd äldre klausultext
  ("Standardavtalsklausuler (SCC) 2021").
- NDA: ömsesidig sekretess, 5 år efter avtalets slut.

### Variety (critical – no identical templates)
Use at least 6 structurally different templates (vary: rubric numbering style,
section order, tables vs prose, preamble style, bilaga usage, footer with page
numbers). Assign templates deterministically by contract kind + hash of id.
Contract lengths should vary 2-8 pages.

## Output 3: contracts_manifest.json
List of entries:
{"doc_id": "DOC-CTR-0001", "path": "contracts/customers/CTR-....docx",
 "dtype": "AVTAL", "title": ..., "created": "<signed date>", "author_id": "P-041"
 or company signer, "entities": [ctr id + counterparty id], "version": "1.0",
 "valid_from": effective_from, "valid_to": expires, "event_ids": [], "note": ""}
doc_id must be unique, stable, sorted by contract id.

## Rules
- Do NOT modify the truth model or any other file. Only create/write:
  generator/data/contracts_supplement.json, generator/docgen/contracts.py,
  generator/data/contracts_manifest.json, contracts/**/*.docx.
- Deterministic: no time-based randomness. Use util.rng() streams.
- Report back: number of records rendered, number of DOCX files, template variety
  used, any contract records whose flags you could not render faithfully.
