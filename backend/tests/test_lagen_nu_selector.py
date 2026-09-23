from app.llm.lagen_nu_selector import LlmLagenNuSelector
from app.services.lagen_nu.selection import (
    HitDecision,
    LagenNuSelectionError,
    SelectableDocument,
    SelectableHit,
    apply_hit_decisions,
    verify_excerpt_span,
)
from app.services.prompt_catalog import default_prompts
from app.services.research.models import ResearchNeed
from tests.test_research import _context


def _need() -> ResearchNeed:
    return ResearchNeed(
        id="followup_2",
        question=(
            "Vilka omständigheter har varit avgörande i HD-avgöranden där 36 § "
            "lett till faktisk jämkning?"
        ),
        why_needed="Behövs för att fastställa de faktorer domstolarna vägt tyngst.",
        source_types=["swedish_case_law"],
    )


def _selector(completer) -> LlmLagenNuSelector:
    prompts = default_prompts("sv")
    return LlmLagenNuSelector(
        completer=completer,
        system_prompt=prompts["research.lagen_nu.select.system"],
        triage_prompt=prompts["research.lagen_nu.select.triage"],
        user_prompt=prompts["research.lagen_nu.select.user"],
        excerpt_system_prompt=prompts["research.lagen_nu.excerpt.system"],
        excerpt_user_prompt=prompts["research.lagen_nu.excerpt.user"],
    )


def _hits() -> list[SelectableHit]:
    return [
        SelectableHit(
            candidate_id="https://lagen.nu/sou/1979:36",
            uri="https://lagen.nu/sou/1979:36",
            title="Konsumenttjänstlag",
            identifier="SOU 1979:36",
            highlight="Kort omnämnande av 36 § avtalslagen.",
            pinpoint=None,
        ),
        SelectableHit(
            candidate_id="https://lagen.nu/dom/nja/2011s357",
            uri="https://lagen.nu/dom/nja/2011s357",
            title="Mefedrondomen (NJA 2011 s. 357)",
            identifier="NJA 2011 s. 357",
            highlight="Narkotikaklassificering av mefedron var avgörande.",
            pinpoint=None,
        ),
        SelectableHit(
            candidate_id="https://lagen.nu/prop/1993/94:196",
            uri="https://lagen.nu/prop/1993/94:196",
            title="Ändringar i aktiebolagslagen (1975:1385) m.m.",
            identifier="Prop. 1993/94:196",
            highlight="Kallelse enligt 36 § aktiebolagslagen.",
            pinpoint=None,
        ),
        SelectableHit(
            candidate_id="https://lagen.nu/prop/1975/76:81",
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            identifier="Prop. 1975/76:81",
            highlight="Syftet med 36 § avtalslagen och de vägledande faktorerna.",
            pinpoint=None,
        ),
    ]


async def test_selector_keeps_travaux_and_drops_noise():
    async def completer(messages, response_model):
        assert "candidate_id" in messages[-1]["content"]
        return response_model(
            decisions=[
                {
                    "candidate_id": "https://lagen.nu/sou/1979:36",
                    "keep": False,
                    "role": "wrong_number",
                    "why": "SOU-nummer, inte 36 §",
                },
                {
                    "candidate_id": "https://lagen.nu/dom/nja/2011s357",
                    "keep": False,
                    "role": "wrong_subject",
                    "why": "narkotika",
                },
                {
                    "candidate_id": "https://lagen.nu/prop/1993/94:196",
                    "keep": False,
                    "role": "wrong_subject",
                    "why": "aktiebolagslag",
                },
                {
                    "candidate_id": "https://lagen.nu/prop/1975/76:81",
                    "keep": True,
                    "role": "travaux",
                    "why": "centrala förarbetena",
                },
            ]
        )

    decisions = await _selector(completer).select_hits(
        need=_need(),
        source_type="swedish_preparatory_works",
        candidates=_hits(),
        context=_context(),
    )
    kept = [item.candidate_id for item in decisions if item.keep]
    assert kept == ["https://lagen.nu/prop/1975/76:81"]
    assert {item.role for item in decisions if not item.keep} == {
        "wrong_number",
        "wrong_subject",
    }


async def test_selector_treats_omitted_candidates_as_drop():
    async def completer(messages, response_model):
        return response_model(
            decisions=[
                {
                    "candidate_id": "https://lagen.nu/prop/1975/76:81",
                    "keep": True,
                    "role": "travaux",
                    "why": "ok",
                }
            ]
        )

    decisions = await _selector(completer).select_hits(
        need=_need(),
        source_type="swedish_preparatory_works",
        candidates=_hits(),
        context=_context(),
    )
    kept = [item.candidate_id for item in decisions if item.keep]
    assert kept == ["https://lagen.nu/prop/1975/76:81"]
    omitted = [item for item in decisions if not item.keep]
    assert {item.candidate_id for item in omitted} == {
        "https://lagen.nu/sou/1979:36",
        "https://lagen.nu/dom/nja/2011s357",
        "https://lagen.nu/prop/1993/94:196",
    }
    assert all(item.why == "omitted_by_selector" for item in omitted)


async def test_excerpt_must_be_a_document_span():
    body = (
        "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
        "avtalets innehåll och omständigheterna vid avtalets tillkomst."
    )
    document = SelectableDocument(
        uri="https://lagen.nu/prop/1975/76:81",
        title="Prop. 1975/76:81",
        identifier="Prop. 1975/76:81",
        pinpoint=None,
        text=("Huvudsakligt innehåll Propositionen föreslår en generalklausul.\n\n" + body),
        highlight="Prop. 1975/76:81",
        truncated=False,
    )

    async def completer(messages, response_model):
        return response_model(excerpt=body, pinpoint="", why="specialmotivering")

    decision = await _selector(completer).select_excerpt(
        need=_need(),
        source_type="swedish_preparatory_works",
        document=document,
        context=_context(),
    )
    assert decision.excerpt == body
    assert verify_excerpt_span(document.text, decision.excerpt, max_chars=16000) == body


async def test_invented_excerpt_is_rejected():
    try:
        verify_excerpt_span(
            "Regeringens proposition nr 81.",
            "Lagstiftaren avsåg att skydda den svagare parten.",
            max_chars=16000,
        )
    except LagenNuSelectionError as exc:
        assert "not a span" in str(exc)
    else:
        raise AssertionError("expected LagenNuSelectionError")


def test_apply_hit_decisions_drops_omitted_and_ignores_unknown_ids():
    hits = _hits()[:1]
    applied = apply_hit_decisions(
        hits,
        [
            HitDecision(
                candidate_id="https://lagen.nu/invented",
                keep=True,
                role="travaux",
                why="ignore me",
            )
        ],
    )
    assert applied == [
        HitDecision(
            candidate_id=hits[0].candidate_id,
            keep=False,
            role="peripheral",
            why="omitted_by_selector",
        )
    ]


def test_lagen_nu_selector_prompts_exist():
    prompts = default_prompts("sv")
    assert "hittar inte på URI" in prompts["research.lagen_nu.select.system"]
    assert "{candidates_json}" in prompts["research.lagen_nu.select.user"]
    assert "Kopiera bara text" in prompts["research.lagen_nu.excerpt.system"]
    assert "{document_text}" in prompts["research.lagen_nu.excerpt.user"]


async def test_preliminary_relevance_survives_selector_boundary():
    candidate = SelectableHit(
        candidate_id="https://lagen.nu/dom/nja/1999s408",
        uri="https://lagen.nu/dom/nja/1999s408",
        title="NJA 1999 s. 408",
        identifier="NJA 1999 s. 408",
        highlight="Frågan gäller jämkning enligt 36 § avtalslagen.",
        pinpoint=None,
    )

    async def completer(messages, response_model):
        assert default_prompts("sv")["research.lagen_nu.select.triage"] in messages[0]["content"]
        return response_model(
            decisions=[
                {
                    "candidate_id": candidate.candidate_id,
                    "keep": True,
                    "role": "potentially_relevant",
                    "why": "Fulltext krävs för att verifiera HD:s skäl.",
                }
            ]
        )

    decisions = await _selector(completer).select_hits(
        need=_need(), source_type="swedish_case_law", candidates=[candidate], context=_context()
    )
    assert decisions == [
        HitDecision(
            candidate_id=candidate.candidate_id,
            keep=True,
            role="potentially_relevant",
            why="Fulltext krävs för att verifiera HD:s skäl.",
        )
    ]
