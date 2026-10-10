"""Unit tests for the SME group voice state machine."""

from __future__ import annotations

import pytest

from app.services.sme_group_voice import GroupVoiceSession


def _session() -> GroupVoiceSession:
    return GroupVoiceSession(
        panel_id="1",
        member_ids={"a", "b", "c"},
        member_names={"a": "Anna", "b": "Bo", "c": "Cecilia"},
    )


def test_name_address_uses_token_boundary():
    session = _session()
    assert session.address_by_name("Hej Bo, vad tycker du?") == "b"
    assert session.address_by_name("bolaget har problem") is None
    assert session.address_by_name("Anna och Cecilia") == "a"


def test_grant_and_release_floor():
    session = _session()
    session.raise_hand("a")
    assert "a" in session.hands
    session.grant_floor("a")
    assert session.floor == "a"
    assert "a" not in session.hands
    session.release_floor()
    assert session.floor is None


def test_hand_while_someone_else_speaks():
    session = _session()
    session.grant_floor("a")
    session.raise_hand("b")
    assert session.floor == "a"
    assert "b" in session.hands
    session.raise_hand("a")  # already speaking
    assert "a" not in session.hands


def test_tool_result_raises_hand_and_marks_source():
    session = _session()
    session.attach_tool_result("b", "search", {"ok": True}, "found it")
    assert "b" in session.hands
    assert session.source_checked.get("b") is True
    assert len(session.shared_results) == 1
    snap = session.snapshot()
    assert snap["source_checked"] == ["b"]
    assert snap["shared_result_count"] == 1


def test_snapshot_includes_floor_name():
    session = _session()
    session.grant_floor("c")
    snap = session.snapshot()
    assert snap["floor"] == "c"
    assert snap["floor_name"] == "Cecilia"
    assert snap["hands"] == []
