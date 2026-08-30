"""Module registry — Fas 1: manifests mount without changing URLs."""

from __future__ import annotations

from app.main import create_app
from app.modules.registry import MODULE_REGISTRY, module_id_for_report_mode


def test_module_registry_keys():
    assert set(MODULE_REGISTRY.keys()) == {"dd", "politik"}


def test_module_id_for_report_mode():
    assert module_id_for_report_mode("dd") == "dd"
    assert module_id_for_report_mode("quick") == "politik"
    assert module_id_for_report_mode("full") == "politik"


def test_module_routes_keep_existing_urls():
    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/dd/campaigns" in paths
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
    assert dd.components == frozenset({"personas", "panel_engine", "spindoctor"})
    assert dd.spindoctor is not None
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
    assert politik.spindoctor is not None
    assert politik.spindoctor.supports_interview is True
    assert "get_report_ssr" in politik.spindoctor.mcp_tool_names
    assert politik.sub_questions_provider is None
