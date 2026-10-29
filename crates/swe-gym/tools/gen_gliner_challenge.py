#!/usr/bin/env python3
"""The manually annotated challenge set (docs/architecture/gliner2-jevspan
-evaluation.md, D3): 50 clauses — 25 real corpus clauses the deterministic
extractor handles, and 25 paraphrased legal formulations it likely misses
(no trigger keywords). Gold spans are annotated BY READING the text,
independently of both the regex generator and GLiNER2 (agent-authored,
reviewable — provenance noted in the output).

Output: benchmarks/gliner_challenge.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_gliner_testset import spans_of  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
BENCH = B / "bench_real_v2.json"
OUT = B / "gliner_challenge.json"

# Paraphrased clauses: no trigger keywords the regex relies on. Gold
# spans annotated by hand. (need_type, clause, [(gold_span, entity_type)])
PARAPHRASES = [
    ("SEVERANCE", "Arbetstagaren ska hållas ekonomiskt skadeslös vid förtida avslut.",
     [("hållas ekonomiskt skadeslös", "SEVERANCE")]),
    ("SEVERANCE_VALUE", "Arbetsgivaren svarar för ett belopp motsvarande ett halvt års fast ersättning.",
     [("ett halvt års fast ersättning", "SEVERANCE_VALUE")]),
    ("TERMINATION_CONDITION", "Anställningen upphör utan föregående underrättelse vid väsentligt avtalsbrott.",
     [("upphör utan föregående underrättelse", "TERMINATION_CONDITION")]),
    ("LIABILITY_CAP", "Parternas sammanlagda ansvar får inte överstiga det årliga kontraktsvärdet.",
     [("får inte överstiga det årliga kontraktsvärdet", "LIABILITY_CAP")]),
    ("NOTICE_PERIOD", "Avtalet kan bringas att upphöra tidigast nittio dagar efter skriftligt meddelande.",
     [("nittio dagar", "NOTICE_PERIOD")]),
    ("RENEWAL", "Om ingen part gör invändning fortlöper samarbetet ytterligare ett år.",
     [("fortlöper samarbetet ytterligare ett år", "RENEWAL")]),
    ("PENALTY", "Vid försening utgår en ersättning om två procent av kontraktsvärdet per påbörjad vecka.",
     [("två procent av kontraktsvärdet per påbörjad vecka", "PENALTY")]),
    ("EXCEPTION", "Ersättningsskyldigheten bortfaller när hindret ligger utanför partens kontroll.",
     [("ligger utanför partens kontroll", "EXCEPTION")]),
    ("PARTY", "Uppdragstagaren och dess dotterbolag är solidariskt förpliktade.",
     [("Uppdragstagaren", "PARTY"), ("dess dotterbolag", "PARTY")]),
    ("MONEY", "Det sammanlagda arvodet uppgår till niohundrafemtiotusen kronor exklusive mervärdesskatt.",
     [("niohundrafemtiotusen kronor", "MONEY")]),
    ("DATE", "Avtalet träder i kraft den första dagen i andra kvartalet.",
     [("första dagen i andra kvartalet", "DATE")]),
    ("NOTICE_PERIOD", "Vardera parten äger rätt att frånträda avtalet med två månaders varsel.",
     [("två månaders varsel", "NOTICE_PERIOD")]),
    ("SEVERANCE", "Vid upphörande på bolagets initiativ utgår kompensation motsvarande ett års ersättning.",
     [("kompensation motsvarande ett års ersättning", "SEVERANCE")]),
    ("LIABILITY_CAP", "Skadan är begränsad till vad som erlagts enligt avtalet under de senaste tolv månaderna.",
     [("vad som erlagts enligt avtalet under de senaste tolv månaderna", "LIABILITY_CAP")]),
    ("TERMINATION_CONDITION", "Båda parter får omedelbart ställa in sina åtaganden om motparten träder i likvidation.",
     [("omedelbart ställa in sina åtaganden", "TERMINATION_CONDITION")]),
    ("PENALTY", "Den dröjsmålsdrabbade ska erlägga en och en halv procent av fakturabeloppet för varje påbörjad månad.",
     [("en och en halv procent av fakturabeloppet", "PENALTY")]),
    ("EXCEPTION", "Åtagandena vilar tillfälligt när fullgörelse hindras av omständigheter som inte rimligen kunnat förutses.",
     [("omständigheter som inte rimligen kunnat förutses", "EXCEPTION")]),
    ("NOTICE_PERIOD", "Uppsägning ska ske skriftligen med iakttagande av en uppsägningstid av ett kvartal.",
     [("ett kvartal", "NOTICE_PERIOD")]),
    ("PARTY", "Beställaren jämte dess koncernbolag äger åberopa samtliga rättigheter enligt detta avtal.",
     [("Beställaren", "PARTY"), ("dess koncernbolag", "PARTY")]),
    ("MONEY", "Arvodet faktureras kvartalsvis i efterskott med ett belopp om sjuttiofem tusen kronor per månad.",
     [("sjuttiofem tusen kronor per månad", "MONEY")]),
    ("RENEWAL", "Har avtalet inte skriftligen avbeställts, anses det förnyat för en tid av ett år.",
     [("förnyat för en tid av ett år", "RENEWAL")]),
    ("SEVERANCE_VALUE", "Vid förtida upphörande äger konsulten rätt till ersättning motsvarande sex fasta månadsarvoden.",
     [("sex fasta månadsarvoden", "SEVERANCE_VALUE")]),
    ("LIABILITY_CAP", "Ingendera parten ansvarar för indirekta förluster, utebliven vinst eller följdskador.",
     [("indirekta förluster, utebliven vinst eller följdskador", "LIABILITY_CAP")]),
    ("TERMINATION_CONDITION", "Avtalet kan avslutas med omedelbar effekt om betalning uteblir trots skriftlig anmaning.",
     [("avslutas med omedelbar effekt", "TERMINATION_CONDITION")]),
    ("DATE", "Samarbetet inleds vid månadsskiftet efter undertecknandet.",
     [("månadsskiftet efter undertecknandet", "DATE")]),
]


def main():
    d = json.load(open(BENCH, encoding="utf-8"))
    texts = {}
    for q in d["questions"]:
        texts.update(q.get("texts", {}))

    # 25 real corpus clauses with deterministic-handleable gold spans.
    corpus_cases = []
    for chunk, text in texts.items():
        spans = spans_of(text)
        if len(spans) >= 2 and len(corpus_cases) < 25:
            corpus_cases.append({
                "clause": text.strip(),
                "source": chunk,
                "gold": [{"span": s, "type": t} for t, s in spans],
            })
    if len(corpus_cases) < 25:
        print(f"WARN: bara {len(corpus_cases)} korpusklausuler", file=sys.stderr)

    challenge = {
        "version": 2,
        "cases": [],
    }
    case_ids = set()
    for c in corpus_cases:
        challenge["cases"].append({
            "case_id": None,  # assigned below
            "kind": "corpus",
            "clause": c["clause"],
            "source": c["source"],
            "need": sorted({g["type"] for g in c["gold"]})[0],
            "gold": c["gold"],
        })
    for need, clause, gold in PARAPHRASES:
        challenge["cases"].append({
            "case_id": None,
            "kind": "paraphrase",
            "clause": clause,
            "source": "manuell (illustrativ formulering)",
            "need": need,
            "gold": [{"span": s, "type": t} for s, t in gold],
        })

    # Unique, stable identities: case_id per clause, span_id per
    # annotated occurrence — never normalized text as a key.
    span_ids = set()
    for i, case in enumerate(challenge["cases"], start=1):
        cid = f"g5-{i:02d}"
        assert cid not in case_ids, f"dubblett case_id {cid}"
        case_ids.add(cid)
        case["case_id"] = cid
        for j, g in enumerate(case["gold"], start=1):
            g["span_id"] = f"{cid}-s{j}"
            assert g["span_id"] not in span_ids, f"dubblett span_id {g['span_id']}"
            span_ids.add(g["span_id"])

    json.dump(challenge, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n_corpus = sum(1 for c in challenge["cases"] if c["kind"] == "corpus")
    n_para = len(challenge["cases"]) - n_corpus
    print(f"utmaningsset v2: {len(challenge['cases'])} klausuler med unika case_id "
          f"({n_corpus} korpus, {n_para} omskrivna), "
          f"{len(span_ids)} guldspann med unika span_id, "
          f"annoterade oberoende av regex och GLiNER2 (agent-författade, granskningsbara)")
    print(f"skrivet: {OUT}")


if __name__ == "__main__":
    main()
