"""Scripted 200-document Tabular Review bench.

Not a live embedding/model measurement. Reports time-to-first-row, scoring
latency, and recall against the scripted golden set.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("CEREBRAS_API_KEY", "offline-benchmark-not-used")
os.environ.setdefault("DEEPSEEK_API_KEY", "offline-benchmark-not-used")
os.environ.setdefault("OPENAI_API_KEY", "offline-benchmark-not-used")
os.environ.setdefault("SUPABASE_URL", "https://offline.invalid")
os.environ.setdefault("LOCAL_AUTH_JWT_SECRET", "offline-benchmark-not-used")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "offline-benchmark-not-used")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.services.tabular_review.benchmark import run_scripted_table


def main() -> None:
    payload = run_scripted_table(document_count=200, columns=("uppsagning", "pris", "forlangning"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
