"""Packaging: manifest + the three delivery zips + overview docs.

A. socialism_ingest.zip      – only what the system under test may read
B. socialism_ground_truth.zip – facit, truth model, provenance, validation report
C. socialism_generator.zip    – all generator code, config, seed, validators
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator import config  # noqa: E402

INGEST_ROOTS = ["accounting", "company", "contracts", "correspondence", "customers",
                "employees", "golden_questions", "invoices", "management", "policies",
                "projects", "suppliers"]
GROUND_TRUTH_ROOTS = ["ground_truth", "validation"]
GENERATOR_ROOTS = ["generator"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_inventory() -> list[dict]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        parts = rel.parts
        if parts[0] in ("generator", "ground_truth", "validation") and \
                not (parts[0] == "generator" and parts[1] == "data"):
            continue
        is_pdf = p.suffix.lower() == ".pdf"
        out.append({
            "path": str(rel),
            "size": p.stat().st_size,
            "sha256": None if is_pdf else sha256(p),
            "pdf_of": None,
            "note": "PDF rendered from DOCX; hash not stable across renderers" if is_pdf else "",
        })
    return out


def public_manifest(inv: list[dict]) -> dict:
    return {
        "benchmark": "SPEC-SME-1.0",
        "version": config.VERSION,
        "seed": config.SEED,
        "generated": "2026-10-18",
        "analysis_date": "2026-10-18",
        "company": "Nordviken Digital AB (fiktivt bolag)",
        "fiscal_years": "FY2025: 2024-10-01–2025-09-30; FY2026: 2025-10-01–2026-09-30",
        "disclaimer": ("Alla företag, personer, organisationsnummer och händelser är "
                       "fiktiva. Likheter med verkliga bolag eller personer är oavsiktliga."),
        "files": inv,
    }


def _zip(files: list[tuple[str, Path]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, path in files:
            z.write(path, arcname)


def build_packages(inv: list[dict]) -> dict:
    out = {}
    # ---- A: ingest ----
    ingest_files: list[tuple[str, Path]] = []
    for root in INGEST_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                ingest_files.append((str(p.relative_to(ROOT)), p))
    # sanitized golden questions (no answerability leakage)
    gq = ROOT / "golden_questions" / "golden_questions.json"
    if gq.exists():
        data = json.loads(gq.read_text(encoding="utf-8"))
        if isinstance(data, list) and data and "answerability" in data[0]:
            for q in data:
                q.pop("answerability", None)
            ingest_files = [(a, b) for a, b in ingest_files if a != str(gq.relative_to(ROOT))]
            tmp = ROOT / "golden_questions" / ".gq_sanitized.json"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            ingest_files.append(("golden_questions/golden_questions.json", tmp))
    # README + public manifest
    readme = ROOT / "README.md"
    if readme.exists():
        ingest_files.append(("README.md", readme))
    pub_manifest = public_manifest(inv)
    tmp_manifest = ROOT / ".manifest_ingest.json"
    tmp_manifest.write_text(json.dumps(pub_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ingest_files.append(("manifest.json", tmp_manifest))
    out["ingest"] = ROOT / config.PACKAGES["ingest"]
    _zip(ingest_files, out["ingest"])

    # ---- B: ground truth ----
    gt_files: list[tuple[str, Path]] = []
    for root in GROUND_TRUTH_ROOTS:
        base = ROOT / root
        if base.exists():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    gt_files.append((str(p.relative_to(ROOT)), p))
    # generator data (facts, manifests, answerability, raw questions)
    for p in sorted((ROOT / "generator" / "data").rglob("*")):
        if p.is_file():
            gt_files.append((str(p.relative_to(ROOT)), p))
    gt_files.append(("golden_questions/golden_questions.json", gq))
    if readme.exists():
        gt_files.append(("README.md", readme))
    out["ground_truth"] = ROOT / config.PACKAGES["ground_truth"]
    _zip(gt_files, out["ground_truth"])

    # ---- C: generator ----
    gen_files: list[tuple[str, Path]] = []
    for root in GENERATOR_ROOTS:
        base = ROOT / root
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                gen_files.append((str(p.relative_to(ROOT)), p))
    if readme.exists():
        gen_files.append(("README.md", readme))
    out["generator"] = ROOT / config.PACKAGES["generator"]
    _zip(gen_files, out["generator"])
    return out


def main() -> None:
    inv = file_inventory()
    (ROOT / "manifest.json").write_text(
        json.dumps(public_manifest(inv), ensure_ascii=False, indent=2), encoding="utf-8")
    pkgs = build_packages(inv)
    for k, p in pkgs.items():
        print(f"{k}: {p.name} ({p.stat().st_size / 1e6:.1f} MB)")
    # cleanup temp
    for tmp in (ROOT / "golden_questions" / ".gq_sanitized.json", ROOT / ".manifest_ingest.json"):
        if tmp.exists():
            tmp.unlink()
    print("manifest.json written with", len(inv), "files")


if __name__ == "__main__":
    main()
