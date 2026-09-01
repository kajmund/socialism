"""Test-only third product module. Must not import dd or politik helpers."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.modules.manifest import ModuleManifest, SpindoctorBinding, SpindoctorSource
from app.modules.report_binding import (
    ReportBinding,
    ReportGenerateContext,
    ReportGenerateResult,
)

_router = APIRouter()


async def load_fixture_spindoctor_source(
    session: AsyncSession, report: Report
) -> SpindoctorSource:
    del session
    return SpindoctorSource(
        report=report,
        payload={"body": report.title},
        bundles=[],
    )


def build_fixture_spindoctor_context(
    source: SpindoctorSource, *, locale: str, title: str
) -> str:
    return f"Fixture-rapport: {title}\nlocale={locale}\npayload={source.payload}"


async def generate_fixture_report(ctx: ReportGenerateContext) -> ReportGenerateResult:
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    html_path = ctx.out_dir / "report.html"
    slots_path = ctx.out_dir / "report.slots.json"
    html_path.write_text(f"<html><body>{ctx.title}</body></html>", encoding="utf-8")
    slots_path.write_text("{}", encoding="utf-8")
    return ReportGenerateResult(
        html_path=html_path,
        slots_path=slots_path,
        timing={"total_seconds": 0.0},
    )


def fixture_manifest() -> ModuleManifest:
    return ModuleManifest(
        id="fixture",
        name="Fixture",
        icon="📄",
        router=_router,
        prompt_namespace="fixture",
        frontend_entry="fixture",
        components=frozenset({"spindoctor", "panel_engine"}),
        report_modes=frozenset({"fixture"}),
        report=ReportBinding(
            source_types=frozenset({"fixture_session"}),
            generate=generate_fixture_report,
        ),
        prompt_defaults_provider=lambda: [
            {
                "key": "fixture.prompt.hello",
                "section": "panel",
                "label": {"sv": "Fixture-hälsning", "en": "Fixture greeting"},
                "hint": {"sv": "", "en": ""},
                "defaults": {
                    "sv": "Hej från fixture-modulen.",
                    "en": "Hello from the fixture module.",
                    "nb": "Hej från fixture-modulen.",
                },
            }
        ],
        spindoctor=SpindoctorBinding(
            source_loader=load_fixture_spindoctor_source,
            context_builder=build_fixture_spindoctor_context,
        ),
    )


def install_fixture_module() -> None:
    from app.modules.registry import MODULE_REGISTRY, assert_unique_report_modes

    MODULE_REGISTRY["fixture"] = fixture_manifest()
    assert_unique_report_modes()


def uninstall_fixture_module() -> None:
    from app.modules.registry import MODULE_REGISTRY

    MODULE_REGISTRY.pop("fixture", None)
