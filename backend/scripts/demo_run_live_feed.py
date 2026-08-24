"""Publish demo run-watch events via the running API server."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trigger demo run-watch events on the running API server",
    )
    parser.add_argument("--run-id", type=int, default=1)
    parser.add_argument("--variant-id", default="a")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    url = (
        f"{args.base_url.rstrip('/')}/runs/{args.run_id}/demo-live-feed"
        f"?variant_id={args.variant_id}&delay_seconds={args.delay}"
    )
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"Demo request failed ({exc.code}): {detail}") from exc

    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    main()
