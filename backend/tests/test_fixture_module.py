"""A third module is a manifest + shared catalog — no dd/politik imports."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.database.models import Report
from app.modules.registry import (
    MODULE_REGISTRY,
    module_id_for_report_mode,
    report_binding_for_mode,
)
from app.modules.report_binding import ReportGenerateContext
from app.serializers import utcnow
from app.services.panel.expert_profiles_store import (
    ensure_expert_profile_defaults,
    get_expert_profile_by_key,
    get_expert_profiles,
)
from app.services.panel.methods import PROTOCOL_METHODS, deliberation_method
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.prompt_store import require_active_prompts
from app.services.spindoctor_context import build_spindoctor_context
from tests.fixture_module import install_fixture_module, uninstall_fixture_module

_FIXTURE_SOURCE = Path(__file__).resolve().parent / "fixture_module.py"
_FORBIDDEN_IMPORT_PREFIXES = (
    "app.services.dd",
    "app.services.spindoctor_dd",
    "app.services.spindoctor_politik",
    "app.services.report.politik_module_report",
    "app.services.report.dd_report",
)


def test_fixture_module_source_has_no_dd_or_politik_imports():
    tree = ast.parse(_FIXTURE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for prefix in _FORBIDDEN_IMPORT_PREFIXES:
            assert not name.startswith(prefix), f"{name} imports {prefix}"


@pytest.mark.asyncio
async def test_third_module_report_panel_and_spindoctor(client_db, tmp_path):
    _client, factory = client_db
    install_fixture_module()
    try:
        assert "fixture" not in {"dd", "politik"}
        assert module_id_for_report_mode("fixture") == "fixture"
        assert MODULE_REGISTRY["fixture"].spindoctor is not None

        async with factory() as db:
            attached = await ensure_expert_profile_defaults(
                db,
                "fixture",
                [{"key": "spinndoctor", "name": "Spinndoktor"}],
            )
            assert attached == 1
            row = await get_expert_profile_by_key(db, "spinndoctor")
            assert row is not None
            assert "fixture" in row.modules
            assert "dd" in row.modules
            fixture_experts = await get_expert_profiles(db, "fixture")
            assert any(item.key == "spinndoctor" for item in fixture_experts)

            now = utcnow()
            report_id = "rpt_fixture"
            db.add(
                Report(
                    id=report_id,
                    customer_id=1,
                    status="succeeded",
                    title="Fixture-rapport",
                    locale="sv",
                    mode="fixture",
                    sources=[{"type": "fixture_session", "session_id": "panel_fix"}],
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.commit()

            report, context = await build_spindoctor_context(db, report_id=report_id)
            assert report.mode == "fixture"
            assert "Fixture-rapport" in context
            assert "Kandidat" not in context
            assert "Körning" not in context

            prompts = await require_active_prompts(db)
            created = await create_panel_session(
                db,
                PanelSessionCreate(
                    config=PanelSessionConfig(
                        protocol="generic_panel",
                        module="fixture",
                        topic="Fixture-ämne",
                        brief="Kort underlag",
                        max_rounds=1,
                        expert_slots=[
                            PanelExpertSlot(
                                slot_id="fin",
                                label="Finansiell analytiker",
                                profile="Siffror",
                            )
                        ],
                    )
                ),
            )
            panel = await get_panel_session(db, created.id)
            assert panel is not None
            method_name = PROTOCOL_METHODS["generic_panel"]
            await deliberation_method(method_name)(db, panel, prompts)
            await db.commit()
            assert panel.status == "succeeded"
            assert panel.result is not None
            assert panel.result["protocol"] == "generic_panel"

        binding = report_binding_for_mode("fixture")
        generated = await binding.generate(
            ReportGenerateContext(
                report_id="rpt_fixture",
                title="Fixture-rapport",
                locale="sv",
                sources=[{"type": "fixture_session", "session_id": "panel_fix"}],
                mode="fixture",
                out_dir=tmp_path / "rpt_fixture",
                session_factory=factory,
            )
        )
        assert generated.html_path.is_file()
        assert "Fixture-rapport" in generated.html_path.read_text(encoding="utf-8")
    finally:
        uninstall_fixture_module()
        assert "fixture" not in MODULE_REGISTRY
