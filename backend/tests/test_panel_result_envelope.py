"""PanelResult envelope and DD adapter."""

from __future__ import annotations

from app.services.panel.methods import DELIBERATION_METHODS, PROTOCOL_METHODS
from app.services.panel.result import (
    dd_panel_result_from_stored,
    envelope_from_dd_panel_result,
    is_panel_result_envelope,
)
from tests.test_dd_report import _sample_result


def test_adapter_round_trips_legacy_and_envelope():
    legacy = _sample_result()
    dumped = legacy.model_dump(mode="json")
    assert not is_panel_result_envelope(dumped)
    from_legacy = dd_panel_result_from_stored(dumped)
    assert from_legacy.summary == legacy.summary
    assert len(from_legacy.scores) == len(legacy.scores)

    envelope = envelope_from_dd_panel_result(legacy)
    assert envelope.schema_version == "1"
    assert envelope.protocol == "dd_panel"
    assert envelope.claims
    from_envelope = dd_panel_result_from_stored(envelope.model_dump(mode="json"))
    assert from_envelope.summary == legacy.summary
    assert [row.score for row in from_envelope.scores] == [row.score for row in legacy.scores]
    assert {n.sub_question_id for n in from_envelope.dissensus} == {
        n.sub_question_id for n in legacy.dissensus
    }


def test_deliberation_methods_register_both_complete_methods():
    assert set(DELIBERATION_METHODS) == {"generic_panel", "structured_scoring"}
    assert PROTOCOL_METHODS == {"generic_panel": "generic_panel"}
    assert "dd_panel" not in PROTOCOL_METHODS
