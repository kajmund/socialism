"""Synthetic labeled controls; these texts make no claims about real Swedish cases."""

from dataclasses import replace
from datetime import UTC, datetime

from app.services.research.models import research_evidence
from tests.research_reuse.snapshots import EVIDENCE


def snapshots() -> list[dict]:
    padding = "Registeruppgifter och administrativa anteckningar utan domslut. " * 20
    samples = [
        ("late-court-decision", "Vad beslutade domstolen slutligen om avtalsvillkoret i TEST-1?", [
            padding + "Domstolens slutliga beslut: avtalsvillkoret jämkas till hälften som oskäligt.",
        ], {"control-0": {"directly_supports_answer": True}}),
        ("title-only", "Vad beslutade domstolen slutligen om avtalsvillkoret i TEST-1?", [
            "Registerrubrik: prövning av oskäligt avtalsvillkor. Inget domslut finns i detta utdrag.",
        ], {"control-0": {"directly_supports_answer": False}}),
        ("party-argument-only", "Vad beslutade domstolen slutligen om avtalsvillkoret i TEST-1?", [
            "Käranden yrkar att avtalsvillkoret ska jämkas till hälften som oskäligt. "
            "Detta är partens yrkande. Domstolens avgörande saknas i detta utdrag.",
        ], {"control-0": {"directly_supports_answer": False}}),
        ("mixed-targets", "Vad beslutade domstolen slutligen om avtalsvillkoret i TEST-1?", [
            "Domstolens slutliga beslut: avtalsvillkoret jämkas till hälften som oskäligt.",
            "Registerrubrik: oskäligt avtalsvillkor. Inget domslut finns i detta utdrag.",
        ], {"control-0": {"directly_supports_answer": True},
            "control-1": {"directly_supports_answer": False}}),
        ("conflicting-dates", "Vilket datum gäller villkoret från enligt de aktuella besluten?", [
            padding + "Aktuellt beslut A om samma avtal TEST-1: det enda ikraftträdandedatumet "
            "är 1 maj 2026, inte 1 juni 2026. Detta är gällande, inte ett historiskt beslut.",
            padding + "Aktuellt beslut B om samma avtal TEST-1: det enda ikraftträdandedatumet "
            "är 1 juni 2026, inte 1 maj 2026. Detta är gällande, inte ett historiskt beslut.",
        ], {"control-0": {"contradicts_current_evidence": True},
            "control-1": {"contradicts_current_evidence": True}}),
    ]
    result = []
    for name, objective, texts, expected in samples:
        items = [replace(research_evidence(
            research_need_id="control", source_type="swedish_case_law", status="found",
            title="TEST-1: avtalsvillkor", excerpt=text, provider="synthetic-control",
        ), evidence_id=f"control-{index}", retrieved_at=datetime(2026, 10, 2, tzinfo=UTC))
            for index, text in enumerate(texts)]
        result.append({
            "name": name, "need": {"question": objective}, "expected": expected,
            "evidence": EVIDENCE.dump_python(items, mode="json"),
        })
    return result
