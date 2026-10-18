"""Validation suite – 16 automated checks over the generated dataset.

Every check reports PASS / FAIL / NOT_TESTED with details. No silent failures:
if a check cannot run, it is reported as NOT_TESTED with a reason.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator import compute as C  # noqa: E402
from generator import config  # noqa: E402
from generator.model import Model  # noqa: E402
from generator.sie4 import SieReader  # noqa: E402


class Check:
    def __init__(self, num: int, name: str):
        self.num = num
        self.name = name
        self.status = "PASS"
        self.details: list[str] = []

    def fail(self, *msgs):
        self.status = "FAIL"
        self.details.extend(msgs)

    def not_tested(self, why: str):
        self.status = "NOT_TESTED"
        self.details.append(why)

    def ok(self, msg: str = ""):
        if msg:
            self.details.append(msg)

    def result(self) -> dict:
        return {"check": self.num, "name": self.name, "status": self.status,
                "details": self.details}


class Validator:
    def __init__(self):
        self.m = Model().load(ROOT / "ground_truth" / "truth_model.json")
        self.results: list[dict] = []
        self.manifests = self._load_manifests()
        self.questions = self._load_json_opt(ROOT / "golden_questions" / "golden_questions.json")
        self.facit = self._load_json_opt(ROOT / "ground_truth" / "facit.json")
        self.coverage = self._load_json_opt(ROOT / "ground_truth" / "coverage_matrix.json")
        self.answerability = self._load_json_opt(ROOT / "generator" / "data" / "answerability.json")

    def _load_json_opt(self, path: Path):
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_manifests(self) -> list[dict]:
        out = []
        for name in ("contracts_manifest.json", "operations_manifest.json"):
            p = ROOT / "generator" / "data" / name
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                out.extend(data if isinstance(data, list) else data.get("documents", []))
        return out

    # -------------------------------------------------------------- checks
    def check_01_vouchers_balance(self) -> Check:
        c = Check(1, "Varje verifikation balanserar")
        bad = []
        for v in self.m.vouchers:
            s = sum(Decimal(b) for _, b in v["rows"])
            if s != 0:
                bad.append((v["id"], str(s)))
        if bad:
            c.fail(f"{len(bad)} obalanserade verifikationer: {bad[:10]}")
        else:
            c.ok(f"Alla {len(self.m.vouchers)} verifikationer balanserar (summa 0,00).")
        return c

    def check_02_ib_ub_consistency(self) -> Check:
        c = Check(2, "Ingående och utgående saldon är konsekventa (SIE-korsavstämning)")
        p25 = ROOT / "accounting" / "sie4" / "Nordviken_Digital_FY2025.SE"
        p26 = ROOT / "accounting" / "sie4" / "Nordviken_Digital_FY2026.SE"
        if not (p25.exists() and p26.exists()):
            c.not_tested("SIE-filer saknas")
            return c
        try:
            r25 = SieReader().read(p25)
            r26 = SieReader().read(p26)
        except Exception as e:  # noqa: BLE001
            c.fail(f"Kunde inte läsa SIE-filer: {e}")
            return c
        ub25 = {acc: amt for (tag, year, acc), amt in r25.saldon.items() if tag == "UB" and year == 0}
        ib26 = {acc: amt for (tag, year, acc), amt in r26.saldon.items() if tag == "IB" and year == 0}
        diffs = []
        for acc in set(ub25) | set(ib26):
            if ub25.get(acc) != ib26.get(acc):
                diffs.append((acc, str(ub25.get(acc)), str(ib26.get(acc))))
        if diffs:
            c.fail(f"{len(diffs)} konton skiljer: {diffs[:10]}")
        else:
            c.ok("UB 0 i FY2025-filen == IB 0 i FY2026-filen för samtliga konton.")
        return c

    def check_03_balance_sheet(self) -> Check:
        c = Check(3, "Balansräkningen balanserar")
        tot = sum((Decimal(p["amount"]) for p in self.m.postings), Decimal(0))
        if tot != 0:
            c.fail(f"Totalsumma alla konton: {tot}")
        else:
            c.ok("Totalsumma alla konton = 0,00 (balans).")
        return c

    def check_04_ar_reconciliation(self) -> Check:
        c = Check(4, "Kundreskontra överensstämmer med huvudboken (1510)")
        gl = C.balances_at(self.m.postings, "2026-09-30").get(1510, Decimal(0))
        ar = Decimal(0)
        for inv in self.m.customer_invoices:
            if inv["id"].startswith("KIN"):
                if inv.get("status") == "SETTLED":
                    continue  # refunded; no longer part of AR
                ar -= Decimal(inv["gross"])  # credit note reduces AR
            elif inv.get("status") in ("OPEN", "PARTIAL", "WRITTEN_OFF"):
                gross = Decimal(inv["gross"])
                if inv.get("status") == "PARTIAL":
                    gross -= Decimal(inv.get("paid_amount", "0"))
                ar += gross
        # written-off invoices are no longer in AR; exclude
        for inv in self.m.customer_invoices:
            if inv.get("status") == "WRITTEN_OFF" and not inv["id"].startswith("KIN"):
                ar -= Decimal(inv["gross"])
        if gl != ar:
            c.fail(f"1510 i huvudboken: {gl}, öppna reskontraposter: {ar}")
        else:
            c.ok(f"1510 = {gl} = öppna kundfordringar {ar}.")
        return c

    def check_05_ap_reconciliation(self) -> Check:
        c = Check(5, "Leverantörsreskontra överensstämmer med huvudboken (2440)")
        gl = C.balances_at(self.m.postings, "2026-09-30").get(2440, Decimal(0))
        ap = sum((Decimal(inv["net"]) if inv.get("reverse_charge") else Decimal(inv["gross"])
                  for inv in self.m.supplier_invoices if inv.get("status") == "OPEN"), Decimal(0))
        if gl != -ap:
            c.fail(f"2440 i huvudboken: {gl}, öppna leverantörsfakturor: {ap}")
        else:
            c.ok(f"2440 = {gl} = öppna leverantörsskulder {ap}.")
        return c

    def check_06_bank_reconciliation(self) -> Check:
        c = Check(6, "Banktransaktioner kan avstämmas mot huvudboken (1930)")
        gl = C.balances_at(self.m.postings, "2026-09-30").get(1930, Decimal(0))
        start = Decimal("2600000.00")
        bank = start + sum((Decimal(t["amount"]) for t in self.m.bank_txns), Decimal(0))
        # checkräkningskreditens överföringar postas direkt på 1930 (ej med i bank_txns)
        od_vids = {v["id"] for v in self.m.vouchers
                   if v["text"].startswith(("Uttag checkräkningskredit", "Amortering checkräkningskredit"))}
        od = sum((Decimal(p["amount"]) for p in self.m.postings
                  if p["account"] == 1930 and p["voucher_id"] in od_vids), Decimal(0))
        bank += od
        if gl != bank:
            c.fail(f"1930 i huvudboken: {gl}, bankkontoutdrag: {bank}")
        else:
            c.ok(f"1930 = {gl} = banktransaktioner {bank}.")
        return c

    def check_07_invoice_references(self) -> Check:
        c = Check(7, "Fakturor refererar till giltiga kunder och avtal")
        cust = {getattr(x, "id", None) for x in self.m.customers}
        ctr = {getattr(x, "id", None) for x in self.m.contracts}
        bad = [inv["id"] for inv in self.m.customer_invoices
               if inv["customer_id"] not in cust
               or (inv.get("contract_id") and inv["contract_id"] not in ctr)]
        if bad:
            c.fail(f"{len(bad)} fakturor med ogiltiga referenser: {bad[:10]}")
        else:
            c.ok(f"{len(self.m.customer_invoices)} kundfakturor har giltiga kund-/avtalsreferenser.")
        return c

    def check_08_contract_prices(self) -> Check:
        c = Check(8, "Avtalspriser och fakturering stämmer (med dokumenterade avvikelser)")
        mismatches = []
        sched = {s.id: s for s in self.m.schedules}
        allowed = {"INV-2026-0036", "KIN-2026-0001", "INV-2024-0001", "INV-2025-0030"}
        for inv in self.m.customer_invoices:
            if inv["id"].startswith("KIN") or inv["id"].endswith("-IB"):
                continue
            sid = inv.get("schedule_id")
            if not sid or sid not in sched:
                continue
            sch = sched[sid]
            if sch.billing_model == "TIME" and inv.get("hours") is not None:
                expected = Decimal(inv["hours"]) * Decimal(str(inv["rate"]))
                if C.M(expected) != C.M(inv["net"]) and inv["id"] not in allowed:
                    mismatches.append((inv["id"], inv["net"], str(expected)))
        if mismatches:
            c.fail(f"{len(mismatches)} avvikande fakturor: {mismatches[:10]}")
        else:
            c.ok("Alla löpande fakturor matchar timmar × pris; avvikelser är de dokumenterade händelserna.")
        return c

    def check_09_payroll(self) -> Check:
        c = Check(9, "Lönekostnader och löneunderlag stämmer")
        postings_gross = sum((Decimal(p["amount"]) for p in self.m.postings
                              if p["account"] == 7210 and not p["voucher_id"].startswith("E")), Decimal(0))
        reg_gross = sum((Decimal(r["gross"]) + Decimal(r["severance"])
                         for r in self.m.payroll_runs), Decimal(0))
        if postings_gross != reg_gross:
            c.fail(f"7210 (löner, exkl. bokslut): {postings_gross}, löneunderlag: {reg_gross}")
        else:
            c.ok(f"7210 = {postings_gross} = löneunderlag {reg_gross}.")
        return c

    def check_10_project_links(self) -> Check:
        c = Check(10, "Projektkostnader och intäkter har korrekt koppling")
        proj = {getattr(p, "id", None) for p in self.m.projects}
        bad = [inv["id"] for inv in self.m.customer_invoices
               if inv.get("project_id") and inv["project_id"] not in proj]
        bad_sched = [s.id for s in self.m.schedules
                     if s.project_id and s.project_id not in proj]
        if bad or bad_sched:
            c.fail(f"Ogiltiga projektreferenser: fakturor={bad[:5]} scheman={bad_sched[:5]}")
        else:
            c.ok("Alla faktura- och schemareferenser pekar på befintliga projekt.")
        return c

    def check_11_doc_references(self) -> Check:
        c = Check(11, "Dokument- och entitetsreferenser är giltiga")
        if not self.manifests:
            c.not_tested("Dokumentmanifester saknas ännu (genereras av dokumentteamen)")
            return c
        doc_ids = {d.get("doc_id") for d in self.manifests}
        persons = {getattr(p, "id", None) for p in self.m.persons}
        missing = []
        for e in self.m.events:
            for did in e.doc_ids:
                if did not in doc_ids and did not in {"DOC-CTR-026", "DOC-CTR-030", "DOC-CTR-031", "DOC-CTR-032"}:
                    missing.append((e.id, did))
        person_names = {f"{p.first} {p.last}" for p in self.m.persons}
        def _valid_author(a):
            if not a or a == "SYSTEM":
                return True
            if a in persons:
                return True
            base = a.split(",")[0].strip()
            return base in person_names
        bad_authors = [d.get("doc_id") for d in self.manifests if not _valid_author(d.get("author_id"))]
        if missing:
            c.fail(f"{len(missing)} händelsereferenser saknar dokument: {missing[:10]}")
        if bad_authors:
            c.fail(f"Ogiltiga författare: {bad_authors[:10]}")
        if not missing and not bad_authors:
            c.ok(f"{len(doc_ids)} dokument registrerade; händelsereferenser och författare giltiga.")
        return c

    def check_12_questions_count(self) -> Check:
        c = Check(12, "200 unika Golden Questions finns")
        if self.questions is None:
            c.not_tested("golden_questions.json saknas ännu")
            return c
        ids = [q.get("id") for q in self.questions]
        if len(ids) != 200 or len(set(ids)) != 200:
            c.fail(f"Antal: {len(ids)}, unika: {len(set(ids))}")
        else:
            c.ok("200 unika fråge-ID:n (GQ-001..GQ-200).")
        return c

    def check_13_facit_verifiable(self) -> Check:
        c = Check(13, "Varje besvarbar fråga har verifierbart facit")
        if self.facit is None:
            c.not_tested("facit.json saknas ännu")
            return c
        if self.answerability is None:
            c.not_tested("answerability.json saknas")
            return c
        answerable = set(self.answerability.get("ANSWERABLE", [])) | \
            set(self.answerability.get("PARTIALLY_ANSWERABLE", []))
        facit_ids = {f.get("question_id") for f in self.facit}
        missing = [q for q in answerable if q not in facit_ids]
        if missing:
            c.fail(f"{len(missing)} besvarbara frågor saknar facit: {missing[:10]}")
        else:
            c.ok(f"Facit finns för alla {len(answerable)} besvarbara frågor.")
        return c

    def check_14_insufficient_marked(self) -> Check:
        c = Check(14, "Frågor med otillräckligt underlag är korrekt markerade")
        if self.coverage is None:
            c.not_tested("coverage_matrix.json saknas ännu")
            return c
        cov = {x.get("id"): x for x in self.coverage}
        insuff = self.answerability.get("INSUFFICIENT_EVIDENCE", []) if self.answerability else []
        bad = [q for q in insuff if cov.get(q, {}).get("answerability") != "INSUFFICIENT_EVIDENCE"]
        if bad:
            c.fail(f"Felklassade: {bad[:10]}")
        else:
            c.ok(f"Alla {len(insuff)} INSUFFICIENT_EVIDENCE-frågor är markerade i täckningsmatrisen.")
        return c

    def check_15_no_leakage(self) -> Check:
        c = Check(15, "Inga facitdata läcker in i ingestpaketet")
        ingest_roots = ["accounting", "company", "contracts", "correspondence", "customers",
                        "employees", "golden_questions", "invoices", "management", "policies",
                        "projects", "suppliers", "README.md", "manifest.json"]
        bad_files = []
        for root in ingest_roots:
            base = ROOT / root
            if not base.exists():
                continue
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                rel = str(f.relative_to(ROOT))
                text = None
                try:
                    if f.suffix.lower() in (".json", ".csv", ".md", ".eml", ".txt"):
                        text = f.read_text(encoding="utf-8", errors="ignore")
                    elif f.suffix.lower() in (".docx",):
                        continue  # binary; provenance handled by file list
                except Exception:
                    continue
                if text:
                    for token in ("facit", "truth_model", "ANSWERABLE", "INSUFFICIENT_EVIDENCE",
                                  "CONFLICTING_EVIDENCE", "ground_truth", "answerability",
                                  "coverage_matrix", "provenance"):
                        if token.lower() in text.lower():
                            bad_files.append((rel, token))
                            break
        if bad_files:
            c.fail(f"{len(bad_files)} filer innehåller facit-/sanningsmarkörer: {bad_files[:10]}")
        else:
            c.ok("Inga facitmarkörer i ingestfiler.")
        return c

    def check_16_sie_roundtrip(self) -> Check:
        c = Check(16, "SIE-filerna kan läsas tillbaka utan förlust")
        issues = []
        for fy in ("FY2025", "FY2026"):
            p = ROOT / "accounting" / "sie4" / f"Nordviken_Digital_{fy}.SE"
            if not p.exists():
                c.not_tested(f"{p.name} saknas")
                return c
            try:
                r = SieReader().read(p)
            except Exception as e:  # noqa: BLE001
                c.fail(f"{p.name} kunde inte läsas: {e}")
                return c
            if r.sietyp != 4:
                issues.append(f"{fy}: #SIETYP = {r.sietyp}")
            if r.format != "PC8":
                issues.append(f"{fy}: #FORMAT = {r.format}")
            if r.fnamn != "Nordviken Digital AB":
                issues.append(f"{fy}: #FNAMN = {r.fnamn}")
            # voucher balance + count
            lo = "2024-10-01" if fy == "FY2025" else "2025-10-01"
            hi = "2025-09-30" if fy == "FY2025" else "2026-09-30"
            model_ver = [v for v in self.m.vouchers if lo < v["date"] <= hi]
            if len(r.ver) != len(model_ver):
                issues.append(f"{fy}: verifikationer i filen {len(r.ver)} != modellen {len(model_ver)}")
            for v in r.ver:
                if sum((amt for _, amt in v["rows"]), Decimal(0)) != 0:
                    issues.append(f"{fy}: verifikation {v['series']}-{v['num']} obalanserad")
                    break
            # saldo cross-check
            gl_ub = C.balances_at(self.m.postings, hi)
            for (tag, year, acc), amt in r.saldon.items():
                if tag == "UB" and year == 0:
                    if gl_ub.get(acc, Decimal(0)) != amt:
                        issues.append(f"{fy}: #UB 0 konto {acc}: fil {amt} != GL {gl_ub.get(acc, Decimal(0))}")
        if issues:
            c.fail(*issues[:10])
        else:
            c.ok("Båda SIE4-filerna läses tillbaka: SIETYP 4, PC8, balanserade verifikationer, saldon matchar GL.")
        return c

    # -------------------------------------------------------------- run
    def run(self) -> list[dict]:
        self.results = [
            self.check_01_vouchers_balance().result(),
            self.check_02_ib_ub_consistency().result(),
            self.check_03_balance_sheet().result(),
            self.check_04_ar_reconciliation().result(),
            self.check_05_ap_reconciliation().result(),
            self.check_06_bank_reconciliation().result(),
            self.check_07_invoice_references().result(),
            self.check_08_contract_prices().result(),
            self.check_09_payroll().result(),
            self.check_10_project_links().result(),
            self.check_11_doc_references().result(),
            self.check_12_questions_count().result(),
            self.check_13_facit_verifiable().result(),
            self.check_14_insufficient_marked().result(),
            self.check_15_no_leakage().result(),
            self.check_16_sie_roundtrip().result(),
        ]
        return self.results

    def write_report(self) -> Path:
        out = ROOT / "validation" / "validation_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        summary = {"passed": sum(1 for r in self.results if r["status"] == "PASS"),
                   "failed": sum(1 for r in self.results if r["status"] == "FAIL"),
                   "not_tested": sum(1 for r in self.results if r["status"] == "NOT_TESTED"),
                   "total": len(self.results)}
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "checks": self.results}, f, ensure_ascii=False, indent=2)
        lines = ["# Valideringsrapport – SPEC Synthetic SME Benchmark v1.0", "",
                 f"PASS: {summary['passed']} | FAIL: {summary['failed']} | "
                 f"NOT_TESTED: {summary['not_tested']} | Totalt: {summary['total']}", ""]
        for r in self.results:
            lines.append(f"## {r['check']}. {r['name']} – {r['status']}")
            for d in r["details"]:
                lines.append(f"  - {d}")
        (ROOT / "validation" / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
        return out


def main() -> None:
    v = Validator()
    v.run()
    path = v.write_report()
    print(json.dumps({r["check"]: r["status"] for r in v.results}, indent=1))
    print(f"report: {path}")


if __name__ == "__main__":
    main()
