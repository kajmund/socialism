"""Top-level generator: build story, run finance engine, export everything.

Usage:  python -m generator.generate
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator.docgen.invoices import generate_invoices  # noqa: E402
from generator.exports import export_all  # noqa: E402
from generator.finance import Engine  # noqa: E402
from generator.sie4 import SieExport  # noqa: E402
from generator.story import build_model  # noqa: E402


def main() -> None:
    print("Building canonical story ...")
    m = build_model()
    # merge supplementary contract records (docs-contracts teammate)
    supp = ROOT / "generator" / "data" / "contracts_supplement.json"
    if supp.exists():
        import json as _json
        from generator.model import Contract
        extra = [_json.loads(_json.dumps(c)) for c in _json.loads(supp.read_text(encoding="utf-8"))]
        existing = {getattr(c, "id", None) for c in m.contracts}
        for c in extra:
            if c["id"] not in existing:
                m.contracts.append(Contract(**c))
        print(f"  merged {len(extra)} supplement contracts (total {len(m.contracts)})")
    print(f"  persons={len(m.persons)} employees={len(m.employees)} "
          f"customers={len(m.customers)} suppliers={len(m.suppliers)} "
          f"projects={len(m.projects)} contracts={len(m.contracts)} "
          f"schedules={len(m.schedules)} streams={len(m.streams)} events={len(m.events)}")
    print("Running finance engine (24 months) ...")
    eng = Engine(m)
    eng.run()
    from generator.budget import build_budgets  # noqa: E402
    build_budgets(m)
    print(f"  vouchers={len(m.vouchers)} postings={len(m.postings)} "
          f"customer_invoices={len(m.customer_invoices)} "
          f"supplier_invoices={len(m.supplier_invoices)} bank_txns={len(m.bank_txns)}")
    print("Exporting SIE4 files ...")
    sie = SieExport(m)
    sie.export("FY2025", ROOT / "accounting" / "sie4" / "Nordviken_Digital_FY2025.SE")
    sie.export("FY2026", ROOT / "accounting" / "sie4" / "Nordviken_Digital_FY2026.SE")
    print("Exporting accounting registers ...")
    export_all(m)
    print("Generating invoice DOCX files ...")
    n_inv = generate_invoices(m)
    print(f"  {len(n_inv)} invoice documents")
    out = ROOT / "ground_truth" / "truth_model.json"
    m.save(out)
    print(f"Saved truth model: {out}")
    print("done")


if __name__ == "__main__":
    main()
