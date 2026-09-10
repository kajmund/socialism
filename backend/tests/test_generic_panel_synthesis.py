"""Structured generic_panel synthesis → PanelResult."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services.panel.engine import _moderator_analysis, run_generic_panel
from app.services.panel.result import PanelResult
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelSessionCreate,
    PanelTurn,
)
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.research import empty_research_structured
from app.services.panel.synthesis import (
    GenericPanelSynthesis,
    SynthesizedClaim,
    panel_result_from_synthesis,
    public_transcript_text,
    synthesize_generic_panel_result,
)
from app.services.prompt_catalog import default_prompts, render_prompt

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Förvärv av målbolag X",
        brief="Kort underlag om kassa och avtal.",
        max_rounds=1,
        expert_slots=[
            PanelExpertSlot(slot_id="fin", label="Finansiell analytiker", profile="Siffror"),
            PanelExpertSlot(slot_id="legal", label="Jurist", profile="Avtal"),
        ],
    )


def _turn(
    turn_id: str,
    speaker: str,
    phase: str,
    content: str,
    *,
    slot_id: str | None = None,
) -> PanelTurn:
    return PanelTurn(
        turn_id=turn_id,
        speaker=speaker,
        phase=phase,  # type: ignore[arg-type]
        content=content,
        slot_id=slot_id,
    )


def _expert_transcript(*, scratchpad: str | None = None) -> list[PanelTurn]:
    turns = [
        _turn("1", "moderator", "opening", "Hur håller kassan?"),
        _turn("2", "Finansiell analytiker", "raise_hand", "JA", slot_id="fin"),
        _turn("3", "Jurist", "raise_hand", "JA", slot_id="legal"),
    ]
    if scratchpad is not None:
        turns.append(
            _turn(
                "4",
                "Finansiell analytiker",
                "scratchpad",
                scratchpad,
                slot_id="fin",
            )
        )
    turns.extend(
        [
            _turn(
                "5",
                "Finansiell analytiker",
                "expert",
                "Kassan täcker 18 månader enligt underlaget.",
                slot_id="fin",
            ),
            _turn(
                "6",
                "Jurist",
                "expert",
                "Avtalen är sedvanliga och utan change-of-control-fällor.",
                slot_id="legal",
            ),
        ]
    )
    return turns


def _install_synthesis(result: GenericPanelSynthesis, captured: list[list[dict]] | None = None):
    async def _complete(messages, response_model):
        if captured is not None:
            captured.append([dict(item) for item in messages])
        if response_model is GenericPanelSynthesis:
            return result
        empty_research = empty_research_structured(response_model)
        if empty_research is not None:
            return empty_research
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(_complete)


@pytest.mark.asyncio
async def test_consensus_becomes_claim_without_dissensus():
    _install_synthesis(
        GenericPanelSynthesis(
            summary="Panelen bedömer att kassan räcker.",
            claims=[
                SynthesizedClaim(
                    claim="Kassan täcker den planerade perioden.",
                    evidence="Båda experterna hänvisade till samma 18-månaderssiffra i underlaget.",
                    judgment="Bedömd slutsats.",
                    dissensus=False,
                )
            ],
        )
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=_expert_transcript(),
        moderator_analysis="Fri analys: kassan ser ut att räcka.",
        prompts=default_prompts("sv"),
    )
    assert result.protocol == "generic_panel"
    assert len(result.claims) == 1
    assert result.claims[0].dissensus is False
    assert result.claims[0].score is None
    assert result.claims[0].claim_id == "claim_1"


@pytest.mark.asyncio
async def test_material_disagreement_sets_dissensus():
    _install_synthesis(
        GenericPanelSynthesis(
            summary="Experterna är oeniga om likviditetsrisken.",
            claims=[
                SynthesizedClaim(
                    claim="Likviditetsrisken är materiell.",
                    evidence="Finans ser 18 månader; juristen menar att covenants kan korta bufferten.",
                    judgment="Materiell oenighet om samma fråga. Ingen röstning.",
                    dissensus=True,
                )
            ],
        )
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=_expert_transcript(),
        moderator_analysis="Oenighet om kassan.",
        prompts=default_prompts("sv"),
    )
    assert result.claims[0].dissensus is True
    assert "oenighet" in result.claims[0].judgment.lower()


@pytest.mark.asyncio
async def test_missing_evidence_becomes_unanswered():
    _install_synthesis(
        GenericPanelSynthesis(
            summary="Underlaget räcker inte för en slutsats om skuldsättning.",
            unanswered=["Skuldsättningen kan inte bedömas — nyckeltal saknas i underlaget."],
        )
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=_expert_transcript(),
        moderator_analysis="Siffror saknas.",
        prompts=default_prompts("sv"),
    )
    assert result.claims == []
    assert result.unanswered == [
        "Skuldsättningen kan inte bedömas — nyckeltal saknas i underlaget."
    ]


@pytest.mark.asyncio
async def test_all_abstain_does_not_fabricate_claims():
    transcript = [
        _turn("1", "moderator", "opening", "Finns det en dold risk?"),
        _turn("2", "Finansiell analytiker", "raise_hand", "NEJ", slot_id="fin"),
        _turn("3", "Jurist", "raise_hand", "NEJ", slot_id="legal"),
    ]
    _install_synthesis(
        GenericPanelSynthesis(
            summary="Ingen expert yttrade sig.",
            claims=[
                SynthesizedClaim(
                    claim="Det finns ingen dold risk.",
                    evidence="Alla experter avstod.",
                    judgment="Feltolkad abstention.",
                )
            ],
            unanswered=["Ingen expert besvarade frågan om dold risk."],
        )
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=transcript,
        moderator_analysis="Alla avstod.",
        prompts=default_prompts("sv"),
    )
    assert result.claims == []
    assert result.unanswered == ["Ingen expert besvarade frågan om dold risk."]
    assert "ingen dold risk" not in result.summary.lower()
    assert result.payload["synthesis"]["claims"] == []


@pytest.mark.asyncio
async def test_single_expert_claim_is_allowed_without_false_consensus():
    transcript = [
        _turn("1", "moderator", "opening", "Hur ser kassan ut?"),
        _turn("2", "Finansiell analytiker", "raise_hand", "JA", slot_id="fin"),
        _turn("3", "Jurist", "raise_hand", "NEJ", slot_id="legal"),
        _turn(
            "4",
            "Finansiell analytiker",
            "expert",
            "Kassan täcker 18 månader enligt underlaget.",
            slot_id="fin",
        ),
    ]
    _install_synthesis(
        GenericPanelSynthesis(
            summary="En expert bedömde kassan. Juristen avstod.",
            claims=[
                SynthesizedClaim(
                    claim="Kassan täcker 18 månader enligt underlaget.",
                    evidence="Finansiell analytiker hänvisade till underlagets likviditetssiffra.",
                    judgment="Ensam bedömning. Panelen har inte enats.",
                    dissensus=False,
                )
            ],
        )
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=transcript,
        moderator_analysis="Bara finans talade.",
        prompts=default_prompts("sv"),
    )
    assert len(result.claims) == 1
    blob = f"{result.summary}\n{result.claims[0].judgment}\n{result.claims[0].claim}"
    assert "enig" not in blob.lower()
    assert "consensus" not in blob.lower()


@pytest.mark.asyncio
async def test_scratchpad_only_statement_is_not_sent_and_not_a_claim():
    secret = "Hemlig scratchpad-slutsats: dold skatteskuld på 40 miljoner."
    captured: list[list[dict]] = []
    _install_synthesis(
        GenericPanelSynthesis(
            summary="Offentlig tur nämner inte skatt.",
            claims=[
                SynthesizedClaim(
                    claim=secret,
                    evidence=secret,
                    judgment="Hämtat från scratchpad.",
                )
            ],
        ),
        captured,
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=_expert_transcript(scratchpad=secret),
        moderator_analysis="Fri analys utan skatt.",
        prompts=default_prompts("sv"),
    )
    prompt_blob = "\n".join(item["content"] for item in captured[0])
    assert secret not in prompt_blob
    assert "scratchpad" not in public_transcript_text(_expert_transcript(scratchpad=secret)).lower()
    assert result.claims == []
    assert secret not in str(result.payload)


@pytest.mark.asyncio
async def test_raise_hand_yes_no_is_not_kept_as_evidence():
    captured: list[list[dict]] = []
    _install_synthesis(
        GenericPanelSynthesis(
            summary="Raise-hand är inte belägg.",
            claims=[
                SynthesizedClaim(
                    claim="JA",
                    evidence="NEJ",
                    judgment="Felaktigt använd turordning.",
                )
            ],
        ),
        captured,
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=_expert_transcript(),
        moderator_analysis="Analys.",
        prompts=default_prompts("sv"),
    )
    prompt_blob = "\n".join(item["content"] for item in captured[0])
    assert "raise_hand" in prompt_blob
    assert result.claims == []
    assert result.payload["synthesis"]["claims"] == []


@pytest.mark.asyncio
async def test_weak_transcript_yields_valid_result_without_hallucinated_claims():
    _install_synthesis(
        GenericPanelSynthesis(
            summary="",
            claims=[
                SynthesizedClaim(
                    claim="Påhittad slutsats.",
                    evidence="Inget underlag.",
                    judgment="Hallucination.",
                )
            ],
            unanswered=["För svagt underlag för att dra slutsatser."],
        )
    )
    result = await synthesize_generic_panel_result(
        config=_config(),
        transcript=[],
        moderator_analysis="",
        prompts=default_prompts("sv"),
    )
    assert result.protocol == "generic_panel"
    assert result.claims == []
    assert result.unanswered == ["För svagt underlag för att dra slutsatser."]
    assert "transcript" not in result.payload
    assert result.payload["synthesis"]["claims"] == []
    assert "Påhittad slutsats" not in str(result.payload)


def test_claim_ids_are_assigned_by_code():
    synthesis = GenericPanelSynthesis(
        summary="Två punkter.",
        claims=[
            SynthesizedClaim(claim="Första slutsatsen.", evidence="A.", judgment="Bedömning."),
            SynthesizedClaim(claim="Andra slutsatsen.", evidence="B.", judgment="Bedömning."),
        ],
    )
    result = panel_result_from_synthesis(synthesis, transcript=_expert_transcript())
    assert [row.claim_id for row in result.claims] == ["claim_1", "claim_2"]
    assert all(row.score is None for row in result.claims)
    assert result.protocol == "generic_panel"
    assert "synthesis" in result.payload
    dumped = result.model_dump(mode="json")
    assert "transcript" not in dumped["payload"]
    assert [row["claim"] for row in dumped["payload"]["synthesis"]["claims"]] == [
        "Första slutsatsen.",
        "Andra slutsatsen.",
    ]
    assert all(row.evidence_refs == [] for row in result.claims)


def test_known_evidence_refs_are_kept_and_unknown_are_dropped():
    synthesis = GenericPanelSynthesis(
        summary="En punkt.",
        claims=[
            SynthesizedClaim(
                claim="Skatten är 32%.",
                evidence="Stöd i [E1] och påhittad [E9].",
                judgment="Bedömning.",
                evidence_refs=["E1", "E9", "nope"],
            )
        ],
    )
    result = panel_result_from_synthesis(
        synthesis,
        transcript=_expert_transcript(),
        allowed_evidence_refs=frozenset({"E1", "E2"}),
    )
    assert result.claims[0].evidence_refs == ["E1"]


def test_claim_without_evidence_or_judgment_is_rejected():
    synthesis = GenericPanelSynthesis(
        summary="Svag rad.",
        claims=[
            SynthesizedClaim(claim="Kassan räcker.", evidence="", judgment="Bedömning."),
            SynthesizedClaim(claim="Avtalen håller.", evidence="Juristen sade så.", judgment=""),
            SynthesizedClaim(
                claim="Bra underlag.",
                evidence="Offentlig tur.",
                judgment="Bedömd slutsats.",
            ),
        ],
    )
    result = panel_result_from_synthesis(synthesis, transcript=_expert_transcript())
    assert [row.claim for row in result.claims] == ["Bra underlag."]
    assert [row["claim"] for row in result.payload["synthesis"]["claims"]] == [
        "Bra underlag."
    ]


@pytest.mark.asyncio
async def test_moderator_analysis_does_not_see_scratchpads():
    secret = "Hemlig scratchpad-slutsats: dold skatteskuld på 40 miljoner."
    seen: list[list[dict]] = []

    async def _complete(messages, *, model=None):
        seen.append([dict(item) for item in messages])
        return "Analys utan scratchpad."

    set_text_completer(_complete)
    text = await _moderator_analysis(
        _config(),
        _expert_transcript(scratchpad=secret),
        default_prompts("sv"),
    )
    assert text == "Analys utan scratchpad."
    blob = "\n".join(item["content"] for item in seen[0])
    assert secret not in blob
    assert "(scratchpad)" not in blob


def test_synthesis_prompt_renders_placeholders():
    text = render_prompt(
        default_prompts("sv"),
        "panel.generic.synthesis",
        topic="Förvärv",
        brief="Underlag",
        expert_list="- Finans",
        transcript="moderator: Hej",
        moderator_analysis="Fri text",
    )
    assert "Förvärv" in text
    assert "Underlag" in text
    assert "Fri text" in text
    assert "moderator: Hej" in text


def test_word_and_structured_scoring_do_not_import_generic_synthesis():
    paths = [
        _BACKEND_ROOT / "app" / "services" / "expertgranskning" / "word_review.py",
        _BACKEND_ROOT / "app" / "services" / "panel" / "structured_scoring.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert "app.services.panel.synthesis" not in imported, path


@pytest.mark.asyncio
async def test_engine_keeps_analysis_and_writes_structured_result(client_db):
    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return "Pad"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return "Kassan håller enligt underlaget."
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri moderatoranalys om kassan."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen."
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    _install_synthesis(
        GenericPanelSynthesis(
            summary="Strukturerad slutsats om kassan.",
            claims=[
                SynthesizedClaim(
                    claim="Kassan håller.",
                    evidence="Offentlig expert tur pekar på underlaget.",
                    judgment="Bedömd slutsats.",
                )
            ],
        )
    )
    set_text_completer(_complete)
    set_tools_completer(_tools)

    _client, factory = client_db
    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        row = await get_panel_session(db, created.id)
        assert row is not None
        await run_generic_panel(db, row, default_prompts("sv"))
        await db.commit()
        assert row.analysis == "Fri moderatoranalys om kassan."
        stored = PanelResult.model_validate(row.result)
        assert stored.protocol == "generic_panel"
        assert stored.summary == "Strukturerad slutsats om kassan."
        assert stored.summary != row.analysis
        assert stored.claims[0].claim_id == "claim_1"
        assert stored.claims[0].score is None
        assert stored.unanswered == []
