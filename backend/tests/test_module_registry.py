"""Module registry — Fas 1: manifests mount without changing URLs."""

from __future__ import annotations

import pytest

from app.main import create_app
from app.modules.manifest import ModuleManifest
from app.modules.registry import (
    MODULE_REGISTRY,
    assert_unique_report_modes,
    module_has_component,
    module_id_for_report_mode,
    report_binding_for_mode,
    resolve_report_mode,
    source_types_for_registry,
)
from app.modules.report_binding import UnknownReportModeError


def test_module_registry_keys():
    assert set(MODULE_REGISTRY.keys()) == {"dd", "politik"}


def test_module_id_for_report_mode():
    assert module_id_for_report_mode("dd") == "dd"
    assert module_id_for_report_mode("quick") == "politik"
    assert module_id_for_report_mode("full") == "politik"


def test_module_id_for_report_mode_unknown_fails_loud():
    with pytest.raises(UnknownReportModeError, match="upphandling"):
        module_id_for_report_mode("upphandling")


def test_resolve_report_mode_from_source_type():
    assert resolve_report_mode("dd_session", None) == "dd"
    assert resolve_report_mode("oasis", None) == "quick"
    assert resolve_report_mode("oasis", "full") == "full"
    with pytest.raises(ValueError, match="not valid"):
        resolve_report_mode("oasis", "dd")
    with pytest.raises(ValueError, match="not valid"):
        resolve_report_mode("dd_session", "quick")
    assert "dd_session" in source_types_for_registry()
    assert "oasis" in source_types_for_registry()


def test_report_binding_for_known_modes():
    dd_binding = report_binding_for_mode("dd")
    assert "dd_session" in dd_binding.source_types
    politik_binding = report_binding_for_mode("quick")
    assert "oasis" in politik_binding.source_types
    assert report_binding_for_mode("full") is politik_binding


def test_assert_unique_report_modes_rejects_collision():
    from fastapi import APIRouter

    colliding = {
        "dd": MODULE_REGISTRY["dd"],
        "other": ModuleManifest(
            id="other",
            name="Other",
            icon="?",
            router=APIRouter(),
            prompt_namespace="other",
            frontend_entry="other",
            report_modes=frozenset({"dd"}),
            report=MODULE_REGISTRY["dd"].report,
        ),
    }
    with pytest.raises(RuntimeError, match="claimed by both"):
        assert_unique_report_modes(colliding)


def test_module_routes_keep_existing_urls():
    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/dd/campaigns" in paths
    assert "/modules" in paths
    assert "/kunder" in paths
    assert "/panel/sub-questions" in paths
    assert "/panel/expert-profiles" in paths
    assert "/runs" in paths
    assert "/personas" in paths
    assert "/populations" in paths
    assert not any(path.startswith("/api/") for path in paths)
    assert "/api/dd" not in paths
    assert "/api/dd/campaigns" not in paths


def test_module_manifest_shapes():
    dd = MODULE_REGISTRY["dd"]
    assert dd.id == "dd"
    assert dd.frontend_entry == "dd"
    assert dd.prompt_namespace == "dd"
    assert dd.components == frozenset({"personas", "panel_engine", "spindoctor", "campaigns"})
    assert dd.report_modes == frozenset({"dd"})
    assert dd.report is not None
    assert dd.spindoctor is not None
    assert dd.spindoctor.source_loader is not None
    assert dd.spindoctor.context_builder is not None
    assert dd.spindoctor.supports_interview is False
    assert "get_report_dd" in dd.spindoctor.mcp_tool_names
    assert dd.sub_questions_provider is not None
    assert dd.expert_defaults_provider is not None
    assert len(dd.sub_questions_provider()) == 4
    assert len(dd.expert_defaults_provider()) == 4

    politik = MODULE_REGISTRY["politik"]
    assert politik.id == "politik"
    assert politik.frontend_entry == "politik"
    assert politik.components == frozenset({"personas", "interview", "spindoctor"})
    assert politik.report_modes == frozenset({"quick", "full"})
    assert politik.report is not None
    assert politik.spindoctor is not None
    assert politik.spindoctor.source_loader is not None
    assert politik.spindoctor.context_builder is not None
    assert politik.spindoctor.supports_interview is True
    assert "get_report_ssr" in politik.spindoctor.mcp_tool_names
    assert politik.sub_questions_provider is None


def test_spindoctor_context_has_no_report_mode_branch():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1] / "app/services/spindoctor_context.py"
    ).read_text(encoding="utf-8")
    assert "if report.mode" not in text
    assert 'report.mode == "dd"' not in text


def test_module_has_component():
    assert module_has_component("dd", "campaigns")
    assert module_has_component("dd", "panel_engine")
    assert not module_has_component("politik", "campaigns")
    assert not module_has_component("unknown", "campaigns")
