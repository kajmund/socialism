"""Precision, recall, sources, and confidence diagnostics. No approval threshold."""

from __future__ import annotations

from overgraph_ingest.doctags.catalog import TAG_CLASSES
from overgraph_ingest.doctags.gold import TAG_GOLDS, gold_keys, golds_for


def summarize(proposals: list[dict[str, object]]) -> dict[str, object]:
    predicted = {
        (str(row["relative_path"]), str(row["tag_class"]), str(row["value"])): row
        for row in proposals
    }
    gold = gold_keys()
    hits = gold & set(predicted)
    extras = set(predicted) - gold
    misses = gold - set(predicted)
    source = _source_scores(hits, predicted)
    return {
        "gold_n": len(gold),
        "predicted_n": len(predicted),
        "hits": len(hits),
        "extras": len(extras),
        "misses": len(misses),
        "precision": _ratio(len(hits), len(predicted)),
        "recall": _ratio(len(hits), len(gold)),
        "per_class": {
            tag_class: _class_scores(tag_class, predicted)
            for tag_class in TAG_CLASSES
        },
        "source": source,
        "normalization_errors": _normalization_errors(predicted),
        "confidence": _confidence(proposals),
        "extra_rows": sorted(extras),
        "miss_rows": sorted(misses),
        "hit_rows": sorted(hits),
    }


def pair_variants(
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    return {
        "precision_delta": _delta(right.get("precision"), left.get("precision")),
        "recall_delta": _delta(right.get("recall"), left.get("recall")),
        "extra_delta": int(right["extras"]) - int(left["extras"]),
        "miss_delta": int(right["misses"]) - int(left["misses"]),
        "source_validated_delta": (
            int(right["source"]["validated"]) - int(left["source"]["validated"])
        ),
    }


def decide(summaries: dict[str, dict[str, object]]) -> dict[str, object]:
    a = summaries.get("A") or {}
    b = summaries.get("B") or {}
    a_hits = int(a.get("hits") or 0)
    b_hits = int(b.get("hits") or 0)
    return {
        "best_variant": "B" if b_hits > a_hits else "A" if a else "B",
        "jev_adds_measurable_quality": b_hits > a_hits,
        "no_quality_threshold": True,
        "confidence_is_not_legal_probability": True,
        "no_automatic_approval_threshold": True,
        "prepared_knowledge_not_legal_proof": True,
        "reason": (
            f"A hits {a.get('hits')} / gold {a.get('gold_n')}, "
            f"B hits {b.get('hits')} / gold {b.get('gold_n')}. "
            "Choose from the table. No quality threshold was set."
        ),
    }


def _class_scores(
    tag_class: str,
    predicted: dict[tuple[str, str, str], dict[str, object]],
) -> dict[str, object]:
    gold = {key for key in gold_keys() if key[1] == tag_class}
    pred = {key for key in predicted if key[1] == tag_class}
    hits = gold & pred
    return {
        "gold_n": len(gold),
        "predicted_n": len(pred),
        "hits": len(hits),
        "extras": len(pred - gold),
        "misses": len(gold - pred),
        "precision": _ratio(len(hits), len(pred)),
        "recall": _ratio(len(hits), len(gold)),
    }


def _source_scores(
    hits: set[tuple[str, str, str]],
    predicted: dict[tuple[str, str, str], dict[str, object]],
) -> dict[str, object]:
    gold_by_key = {item.key(): item for item in TAG_GOLDS}
    validated = 0
    passage_ok = 0
    unvalidated = 0
    wrong_passage = 0
    for key in hits:
        source = dict(predicted[key].get("source") or {})
        gold = gold_by_key[key]
        excerpt = str(source.get("excerpt") or "")
        ok = bool(source.get("validated"))
        contains = gold.contains.casefold() in excerpt.casefold()
        if ok and contains:
            validated += 1
            passage_ok += 1
        elif ok:
            validated += 1
            wrong_passage += 1
        else:
            unvalidated += 1
    return {
        "hits": len(hits),
        "validated": validated,
        "passage_ok": passage_ok,
        "unvalidated": unvalidated,
        "wrong_passage": wrong_passage,
        "position_is_not_legal_proof": True,
    }


def _normalization_errors(
    predicted: dict[tuple[str, str, str], dict[str, object]],
) -> list[dict[str, object]]:
    errors = []
    for path in {key[0] for key in predicted}:
        golds = golds_for(path)
        for tag_class in {item.tag_class for item in golds}:
            gold_values = {item.value for item in golds if item.tag_class == tag_class}
            pred_values = {
                key[2]
                for key in predicted
                if key[0] == path and key[1] == tag_class
            }
            extras = pred_values - gold_values
            if extras and gold_values:
                errors.append(
                    {
                        "relative_path": path,
                        "tag_class": tag_class,
                        "predicted": sorted(extras),
                        "gold": sorted(gold_values),
                    }
                )
    return errors


def _confidence(proposals: list[dict[str, object]]) -> dict[str, object]:
    values = [
        float(row["confidence"])
        for row in proposals
        if isinstance(row.get("confidence"), (int, float))
    ]
    return {
        "n": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "not_calibrated_legal_probability": True,
        "not_used_as_threshold": True,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _delta(right: object, left: object) -> float | None:
    if right is None or left is None:
        return None
    return float(right) - float(left)
