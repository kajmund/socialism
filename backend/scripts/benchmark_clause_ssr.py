"""Scripted clause-SSR holdout benchmark. Not a live model measurement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.knowledge.scope import shared_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.clause_ssr.benchmark import score_holdout
from tests.clause_ssr_fakes import embedding_spec
from tests.test_clause_ssr_benchmark import EXPECTED, _library, _seed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path("data/clause-ssr-bench"))
    args = parser.parse_args()
    catalog = open_catalog(args.dir / "knowledge", kind="knowledge", dimension=32)
    _seed(catalog)
    report: dict[str, object] = {}
    for labeled in (2, 4):
        _library(catalog, labeled)
        report[str(labeled)] = score_holdout(
            catalog,
            scope=shared_scope(),
            embedding=embedding_spec(),
            expected=EXPECTED,
        )
    print(json.dumps({"scripted": True, "live_model": False, "after_labels": report}, indent=2))


if __name__ == "__main__":
    main()
