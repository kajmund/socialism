"""CLI entry so `python ingest.py` works after `uv sync`."""

from overgraph_ingest.ingest import main

if __name__ == "__main__":
    raise SystemExit(main())
