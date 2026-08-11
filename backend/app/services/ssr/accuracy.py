"""SSR calibration accuracy helpers."""


def macro_accuracy(predicted: list[str], actual: list[str]) -> float:
    """Mean per-label hit rate (only labels present in ``actual``)."""
    by_label: dict[str, list[bool]] = {}
    for pred, act in zip(predicted, actual, strict=True):
        by_label.setdefault(act, []).append(pred == act)
    if not by_label:
        return 0.0
    rates = [sum(hits) / len(hits) for hits in by_label.values()]
    return sum(rates) / len(rates)
