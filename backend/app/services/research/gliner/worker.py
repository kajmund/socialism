"""GLiNER2 worker process: one model load per process, JSON-lines protocol.

The proposer spawns this module in a child process so a timeout can actually
stop the model work (the process is killed) instead of leaving a thread
running behind a cancelled await. The model is loaded once when the process
starts and reused for every request until the process is killed.

Exit codes carry the failure class without broad exception handling:
  3 = missing runtime dependencies (gliner2 not installed)
  anything else = load/inference failure; the parent reads stderr.

Protocol (one JSON object per line):
  ready:   {"ok": true, "ready": true}
  request: {"units": [{"unit_id": "...", "text": "..."}], "labels": [...],
            "threshold": 0.3}
  reply:   {"ok": true, "result": [{"unit_id": "...", "proposals":
            [{"span": "...", "label": "..."}]}]}
  error:   {"ok": false, "reason": "...", "error": "..."}
"""

from __future__ import annotations

import json
import sys


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle_line(model: object, line: str) -> dict[str, object]:
    """Answer one request line. Model failures crash the process (the parent
    reports them as a typed error); malformed requests answer explicitly."""
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": "invalid_request", "error": str(exc)}
    request_id = request.get("request_id")
    result = []
    for unit in request.get("units", []):
        raw = model.extract_entities(
            unit["text"],
            entity_types=request.get("labels", []),
            threshold=float(request.get("threshold", 0.3)),
            format_results=False,
        )
        proposals = []
        for entry in raw.get("entities", []):
            for label, spans in entry.items():
                proposals.extend({"span": span, "label": label} for span in spans)
        result.append({"unit_id": unit["unit_id"], "proposals": proposals})
    return {"ok": True, "request_id": request_id, "result": result}


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("gliner worker: model name required\n")
        return 2
    try:
        from gliner2 import AutoExtractor  # heavy optional dependency
    except ImportError:
        return 3
    model = AutoExtractor.from_pretrained(sys.argv[1])
    _emit({"ok": True, "ready": True})
    for line in sys.stdin:
        if line.strip():
            _emit(_handle_line(model, line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
