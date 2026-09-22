"""Keep claim citations once per reviewer input, without changing frozen evidence."""

import hashlib
import json
from collections.abc import Sequence


def compact_claims(claims: Sequence[dict[str, object]]) -> dict[str, object]:
    citations: dict[str, dict[str, object]] = {}
    rows = []
    for claim in claims:
        refs = []
        for citation in claim.get("citations", []):
            key = hashlib.sha256(json.dumps(citation, sort_keys=True).encode()).hexdigest()[:20]
            citations[key] = citation
            refs.append(key)
        rows.append(
            {key: value for key, value in claim.items() if key != "citations"}
            | {"citation_ids": refs}
        )
    return {"claims": rows, "claim_citations": citations}
