"""Additional labeled controls for boundaries and temporal fact comparisons."""

from copy import deepcopy

from tests.research_reuse.jev_controls import snapshots as initial_snapshots


def snapshots() -> list[dict]:
    cases = initial_snapshots()
    cases[-1]["kind"] = "pair"
    late = deepcopy(cases[0])
    late["name"] = "late-third-window"
    late["evidence"][0]["excerpt"] = (
        "Registeruppgifter utan domslut. " * 100
        + "Domstolens slutliga beslut: avtalsvillkoret jämkas till hälften som oskäligt."
    )
    late["support_span"] = {
        "start": len("Registeruppgifter utan domslut. " * 100),
        "end": len(late["evidence"][0]["excerpt"]),
    }
    cases.append(late)
    pairs = [
        ("matching-dates", [
            "Aktuellt beslut A: samma avtal TEST-1 har endast ikraftträdandedatumet 1 maj 2026.",
            "Aktuellt beslut B: samma avtal TEST-1 har endast ikraftträdandedatumet 1 maj 2026.",
        ]),
        ("historical-change", [
            "Historiskt beslut A om avtal TEST-1: den gamla versionen gällde från 1 maj 2025 "
            "till 31 december 2025. Den har ersatts och är inte längre gällande.",
            "Aktuellt beslut B om avtal TEST-1: den efterföljande versionen gäller från "
            "1 januari 2026. Den ersätter den tidigare versionen från 2025.",
        ]),
        ("different-contracts", [
            "Aktuellt beslut om avtal TEST-1: ikraftträdandedatumet är 1 maj 2026.",
            "Aktuellt beslut om ett annat avtal TEST-2: ikraftträdandedatumet är 1 juni 2026.",
        ]),
    ]
    for name, texts in pairs:
        case = deepcopy(cases[4])
        case["name"] = name
        for index, text in enumerate(texts):
            case["evidence"][index]["excerpt"] = text
            case["expected"][f"control-{index}"]["contradicts_current_evidence"] = False
        cases.append(case)
    return cases
