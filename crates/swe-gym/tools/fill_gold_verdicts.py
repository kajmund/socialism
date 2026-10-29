#!/usr/bin/env python3
"""One-off fill: verify the clean gold spans with arm D's prompt and add
them to the frozen fixture (they replaced the malformed bracket-gold
spans after the generator fix). Bounded, idempotent — existing keys
replay.

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/fill_gold_verdicts.py
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_gliner_challenge import env_value, normalize  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE_PATH = B / "jev_span_fixtures.json"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}
CONTRASTS = {
    "Uppsägningstid": "En uppsägningstid är inte samma sak som avtalstid, förlängningsperiod eller betalningsfrist.",
    "Förlängning": "En förlängningsperiod är inte samma sak som uppsägningstid eller avtalstid.",
}


def fixture_key(case_id, span, version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]
    fixture = json.load(open(FIXTURE_PATH, encoding="utf-8"))
    store = {e["key"]: e for e in fixture["entries"]}
    new = 0
    for case in cases:
        cid = case["case_id"]
        need = NEED_LABELS[case["need"]]
        contrast = CONTRASTS.get(need, "Bedöm enbart spannet.")
        for g in case["gold"]:
            k = fixture_key(cid, g["span"], "span-need-contrast-v1")
            if k in store:
                continue
            instructions = (
                f"Utgör det exakta spannet '{g['span']}' ett {need} för det "
                f"angivna avtalet? {contrast}"
            )
            body = json.dumps({
                "model": model,
                "state": {"text": case["clause"]},
                "questions": {
                    "evidence": {
                        "type": "choice",
                        "instructions": instructions,
                        "criteria": {
                            "YES": "Spannet utgör exakt det efterfrågade sakförhållandet.",
                            "NO": "Spannet utgör inte det efterfrågade sakförhållandet.",
                            "UNCERTAIN": "Går inte att avgöra.",
                        },
                    }
                },
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/v1/systemone",
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                row = json.loads(resp.read().decode("utf-8"))["answers"]["evidence"]
            store[k] = {
                "key": k,
                "case_id": cid,
                "span": g["span"],
                "clause": case["clause"],
                "prompt_version": "span-need-contrast-v1",
                "model": model,
                "choice": row.get("choice"),
                "score_bp": row.get("score_bp"),
                "ts": int(time.time()),
            }
            new += 1
    fixture["entries"] = sorted(store.values(), key=lambda e: e["key"])
    json.dump(fixture, open(FIXTURE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{new} nya guldspann-verifikationer")


if __name__ == "__main__":
    main()
