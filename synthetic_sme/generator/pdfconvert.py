"""Batch DOCX -> PDF conversion via LibreOffice (headless).

Usage: python -m generator.pdfconvert [--scope invoices_fy26|contracts|all]
PDFs are rendered artifacts of the deterministic DOCX sources (their internal
timestamps are not hash-stable; the manifest hashes the DOCX).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def convert_dir(src: Path, soffice: str = "soffice") -> int:
    docx = [p for p in src.rglob("*.docx") if not p.name.startswith("~$")]
    if not docx:
        return 0
    n = 0
    for p in docx:
        outdir = p.parent
        existing = outdir / (p.stem + ".pdf")
        if existing.exists():
            n += 1
            continue
        r = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(p)],
            capture_output=True, timeout=300)
        if r.returncode == 0:
            n += 1
        else:
            print(f"FAILED: {p}: {r.stderr.decode(errors='ignore')[:200]}")
    return n


def main() -> None:
    scope = sys.argv[1] if len(sys.argv) > 1 else "all"
    targets = []
    if scope in ("all", "contracts"):
        targets.append(ROOT / "contracts")
    if scope in ("all", "invoices_fy26"):
        targets.append(ROOT / "invoices" / "outgoing" / "2026")
        targets.append(ROOT / "invoices" / "incoming" / "2026")
    if scope == "invoices_all":
        targets.append(ROOT / "invoices")
    total = 0
    for t in targets:
        if t.exists():
            total += convert_dir(t)
    print(f"converted/verified {total} PDF files")


if __name__ == "__main__":
    main()
