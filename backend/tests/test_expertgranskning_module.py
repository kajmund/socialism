"""Expertgranskning is a real third module — free text, generic_panel, report, Spinndoktor."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer, set_tools_completer
from app.modules.registry import (
    MODULE_REGISTRY,
    module_id_for_report_mode,
    report_binding_for_mode,
    resolve_report_mode,
)
from app.modules.report_binding import ReportGenerateContext
from app.services import jobs as jobs_service
from app.services.expertgranskning import MODULE_ID, REPORT_MODE, SOURCE_TYPE
from app.services.kund_store import (
    BOLAG_DEMO_KUND_SLUG,
    OS_DEFAULT_KUND_SLUG,
    default_os_customer_id,
)
from tests.conftest import BOLAG_USER_ID, mint_access_token
from app.services.panel.expert_profiles_store import get_expert_profile_by_key
from app.services.prompt_fields_store import get_prompt_field_by_key
from app.services.spindoctor_context import build_spindoctor_context

_MODULE_ROOT = Path(__file__).resolve().parents[1] / "app"
_FORBIDDEN_IMPORT_PREFIXES = (
    "app.services.dd",
    "app.services.spindoctor_dd",
    "app.services.spindoctor_politik",
    "app.services.report.politik_module_report",
    "app.services.report.dd_report",
)
_OWNED_PATHS = (
    _MODULE_ROOT / "services" / "expertgranskning",
    _MODULE_ROOT / "api" / "expertgranskning.py",
)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_expertgranskning_source_has_no_dd_or_politik_imports():
    files: list[Path] = []
    for path in _OWNED_PATHS:
        if path.is_file():
            files.append(path)
        else:
            files.extend(path.glob("*.py"))
    assert files
    for path in files:
        for name in _imported_modules(path):
            for prefix in _FORBIDDEN_IMPORT_PREFIXES:
                assert not name.startswith(prefix), f"{path} imports {name}"


def test_expertgranskning_is_registered():
    assert MODULE_ID in MODULE_REGISTRY
    module = MODULE_REGISTRY[MODULE_ID]
    assert module_id_for_report_mode(REPORT_MODE) == MODULE_ID
    assert resolve_report_mode(SOURCE_TYPE, None) == REPORT_MODE
    binding = report_binding_for_mode(REPORT_MODE)
    assert SOURCE_TYPE in binding.source_types
    assert module.report is not None
    assert module.spindoctor is not None
    assert module.spindoctor.supports_interview is False
    assert "panel_engine" in module.components
    assert "spindoctor" in module.components
    assert "campaigns" not in module.components


@pytest.fixture
def mock_panel_llm():
    counters = {"n": 0}

    async def _complete(messages, *, model=None):
        counters["n"] += 1
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return f"Anteckning {counters['n']}"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return f"Inlägg {counters['n']}"
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Syntes: dokumentet är tydligt men behöver skärpas."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen till dokumentgranskningen."
        if "Det här är delfråga" in user or "This is sub-question" in user:
            return "Nästa fråga: håller underlaget?"
        return f"Svar {counters['n']}"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    yield
    set_text_completer(None)
    set_tools_completer(None)


async def _create_expert_panel(client: AsyncClient) -> int:
    from tests.conftest import BOLAG_USER_ID, mint_access_token

    listed = await client.get("/kunder")
    assert listed.status_code == 200
    bolag_id = next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    expert_ids = [row["id"] for row in experts.json()[:2]]
    assert len(expert_ids) >= 2
    admin_auth = client.headers.get("Authorization")
    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=BOLAG_USER_ID, email='bolag@test.local')}"
    )
    try:
        created = await client.post(
            "/populations",
            json={
                "kind": "expert_panel",
                "name": "Expertgranskning testpanel",
                "include_persona_ids": expert_ids,
                "recipe": {"size": len(expert_ids), "dist": {}},
            },
        )
    finally:
        if admin_auth is not None:
            client.headers["Authorization"] = admin_auth
        else:
            client.headers.pop("Authorization", None)
    assert created.status_code == 201, created.text
    return created.json()["id"]


@pytest.mark.asyncio
async def test_expertgranskning_session_report_and_spindoctor(
    client: AsyncClient,
    mock_panel_llm,
    tmp_path,
):
    panel_id = await _create_expert_panel(client)
    document = "Detta PM föreslår en ny kommunikationslinje för höstens kampanj."
    created = await client.post(
        "/expertgranskning/sessions",
        json={
            "document_text": document,
            "panel_id": panel_id,
            "title": "Höstens kampanjlinje",
            "review_intent": "Det är Devbrains som är motpart i avtalet.",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    session_id = body["id"]
    assert body["module"] == MODULE_ID
    assert body["protocol"] == "generic_panel"
    assert body["document_text"] == document
    assert body["panel_id"] == panel_id
    assert body["topic"] == "Höstens kampanjlinje"
    assert body["review_intent"] == "Det är Devbrains som är motpart i avtalet."

    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)
    try:
        run = await client.post(f"/expertgranskning/sessions/{session_id}/run")
        assert run.status_code == 202, run.text
        await asyncio.wait_for(done.wait(), timeout=10)

        session = await client.get(f"/expertgranskning/sessions/{session_id}")
        assert session.status_code == 200
        assert session.json()["status"] == "succeeded"

        factory = jobs_service.job_session_factory()
        assert factory is not None
        binding = report_binding_for_mode(REPORT_MODE)
        generated = await binding.generate(
            ReportGenerateContext(
                report_id="rpt_expertgranskning",
                title="Höstens kampanjlinje",
                locale="sv",
                sources=[{"type": SOURCE_TYPE, "session_id": session_id}],
                mode=REPORT_MODE,
                out_dir=tmp_path / "rpt_expertgranskning",
                session_factory=factory,
            )
        )
        html = generated.html_path.read_text(encoding="utf-8")
        assert generated.html_path.is_file()
        assert "Höstens kampanjlinje" in html
        assert document not in html
        assert 'id="dokument"' not in html
        assert "Devbrains" in html
        assert "Granskningsavsikt" in html
        assert "EXPERTGRANSKNING" in html
        payload_path = tmp_path / "rpt_expertgranskning" / "report.expertgranskning.json"
        assert payload_path.is_file()
        assert document in payload_path.read_text(encoding="utf-8")

        jobs_service.set_schedule_hook(lambda _job_id: None)
        report = await client.post(
            "/reports",
            json={
                "sources": [{"type": SOURCE_TYPE, "session_id": session_id}],
                "title": "Via API",
            },
        )
        assert report.status_code == 202, report.text
        assert report.json()["mode"] == REPORT_MODE
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_expertgranskning_spindoctor_reads_freetext(client_db, tmp_path, monkeypatch):
    _client, factory = client_db
    from app.database.models import Report
    from app.serializers import utcnow
    from app.services.expertgranskning.report_html import write_expertgranskning_artifacts

    artifact_root = tmp_path / "reports"
    monkeypatch.setattr("app.services.report.ARTIFACT_ROOT", str(artifact_root))

    report_id = "rpt_eg_context"
    write_expertgranskning_artifacts(
        out_dir=artifact_root / report_id,
        title="Fritext-rapport",
        locale="sv",
        session_id="panel_eg",
        panel_id=1,
        document_text="Klistrad policytext om skolskjuts.",
        summary="Panelen vill förtydliga ansvar.",
        transcript=[
            {"speaker": "moderator", "phase": "opening", "content": "Välkomna."},
            {"speaker": "Jurist", "phase": "expert", "content": "Ansvaret är otydligt."},
        ],
    )

    async with factory() as db:
        now = utcnow()
        db.add(
            Report(
                id=report_id,
                customer_id=1,
                status="succeeded",
                title="Fritext-rapport",
                locale="sv",
                mode=REPORT_MODE,
                sources=[{"type": SOURCE_TYPE, "session_id": "panel_eg"}],
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()

        report, context = await build_spindoctor_context(db, report_id=report_id)
        assert report.mode == REPORT_MODE
        assert "Expertgranskning-rapport" in context
        assert "Klistrad policytext om skolskjuts." in context
        assert "Panelen vill förtydliga ansvar." in context
        assert "Kandidat" not in context
        assert "Körning" not in context


@pytest.mark.asyncio
async def test_expertgranskning_shares_spinndoctor_catalog(client_db):
    _client, factory = client_db
    async with factory() as db:
        customer_id = await default_os_customer_id(db)
        row = await get_expert_profile_by_key(
            db, "spinndoctor", customer_id=customer_id
        )
        assert row is not None
        assert MODULE_ID in row.modules
        assert "dd" in row.modules
        assert "politik" in row.modules

        prompt = await get_prompt_field_by_key(db, "panel.expert.system")
        assert prompt is not None
        assert MODULE_ID in prompt.modules
        help_prompt = await get_prompt_field_by_key(db, "help.system")
        assert help_prompt is not None
        assert MODULE_ID not in help_prompt.modules
        dd_only = await get_prompt_field_by_key(db, "panel.dd.moderator.system")
        assert dd_only is not None
        assert MODULE_ID not in dd_only.modules


@pytest.mark.asyncio
async def test_non_admin_denied_when_panel_experts_span_kunder(client: AsyncClient):
    from app.services.kund_store import OS_DEFAULT_KUND_SLUG
    from tests.conftest import BOLAG_USER_ID, mint_access_token

    listed = await client.get("/kunder")
    assert listed.status_code == 200
    kunder = {row["slug"]: row["id"] for row in listed.json()}
    os_id = kunder[OS_DEFAULT_KUND_SLUG]
    bolag_id = kunder[BOLAG_DEMO_KUND_SLUG]

    os_expert = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": os_id,
            "name": "OS-expert blandad panel",
            "occ": "Jurist",
            "district": "—",
            "quote": "Granskar text.",
        },
    )
    assert os_expert.status_code == 201, os_expert.text
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    bolag_expert_id = experts.json()[0]["id"]

    created = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": "Mixed-kund panel",
            "include_persona_ids": [os_expert.json()["id"], bolag_expert_id],
            "recipe": {"size": 2, "dist": {}},
        },
    )
    assert created.status_code == 201, created.text
    panel_id = created.json()["id"]

    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=BOLAG_USER_ID, email='bolag@test.local')}"
    )
    denied = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "En text", "panel_id": panel_id},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "kund_access_denied"


@pytest.mark.asyncio
async def test_non_admin_denied_when_patch_attaches_mixed_kund_panel(client: AsyncClient):
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    kunder = {row["slug"]: row["id"] for row in listed.json()}
    os_id = kunder[OS_DEFAULT_KUND_SLUG]
    bolag_id = kunder[BOLAG_DEMO_KUND_SLUG]

    os_expert = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": os_id,
            "name": "OS-expert patch-test",
            "occ": "Jurist",
            "district": "—",
            "quote": "Granskar text.",
        },
    )
    assert os_expert.status_code == 201, os_expert.text
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    bolag_expert_id = experts.json()[0]["id"]

    mixed_panel = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": "Mixed-kund panel patch",
            "include_persona_ids": [os_expert.json()["id"], bolag_expert_id],
            "recipe": {"size": 2, "dist": {}},
        },
    )
    assert mixed_panel.status_code == 201, mixed_panel.text
    mixed_panel_id = mixed_panel.json()["id"]

    own_panel_id = await _create_expert_panel(client)
    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=BOLAG_USER_ID, email='bolag@test.local')}"
    )
    created = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "Egen kundtext", "panel_id": own_panel_id},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    denied = await client.patch(
        f"/expertgranskning/sessions/{session_id}",
        json={"panel_id": mixed_panel_id},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "kund_access_denied"


@pytest.mark.asyncio
async def test_bolag_user_can_create_session_for_own_kund_panel(client: AsyncClient):
    from tests.conftest import BOLAG_USER_ID, mint_access_token

    panel_id = await _create_expert_panel(client)
    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=BOLAG_USER_ID, email='bolag@test.local')}"
    )
    created = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "Egen kundtext", "panel_id": panel_id},
    )
    assert created.status_code == 201, created.text
    assert created.json()["document_text"] == "Egen kundtext"


@pytest.mark.asyncio
async def test_expertgranskning_draft_without_panel_and_missing_panel(client: AsyncClient):
    draft = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "", "title": "Tomt utkast"},
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["status"] == "draft"
    assert body["panel_id"] is None
    assert body["topic"] == "Tomt utkast"
    assert body["document_text"] == ""

    missing_panel = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "En text", "panel_id": 999999},
    )
    assert missing_panel.status_code == 404

    run = await client.post(f"/expertgranskning/sessions/{body['id']}/run")
    assert run.status_code == 400


@pytest.mark.asyncio
async def test_expertgranskning_list_patch_delete(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    created = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "Första version", "panel_id": panel_id, "title": "Lista-test"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    listed = await client.get("/expertgranskning/sessions")
    assert listed.status_code == 200
    rows = listed.json()
    assert any(row["id"] == session_id for row in rows)
    match = next(row for row in rows if row["id"] == session_id)
    assert match["topic"] == "Lista-test"
    assert match["status"] == "draft"
    assert match["panel_id"] == panel_id
    assert match["panel_name"]

    patched = await client.patch(
        f"/expertgranskning/sessions/{session_id}",
        json={
            "document_text": "Uppdaterad text",
            "title": "Nytt namn",
            "review_intent": "Devbrains är motpart i avtalet.",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["document_text"] == "Uppdaterad text"
    assert patched.json()["topic"] == "Nytt namn"
    assert patched.json()["review_intent"] == "Devbrains är motpart i avtalet."

    deleted = await client.delete(f"/expertgranskning/sessions/{session_id}")
    assert deleted.status_code == 204
    gone = await client.get(f"/expertgranskning/sessions/{session_id}")
    assert gone.status_code == 404
    listed_after = await client.get("/expertgranskning/sessions")
    assert all(row["id"] != session_id for row in listed_after.json())


@pytest.mark.asyncio
async def test_admin_with_kund_keeps_underlag_and_panel_on_same_kund(client_db):
    """Admin bound to a kund must not attach underlag to another kund's panel."""
    from app.database.models import UserAccount
    from tests.conftest import ADMIN_USER_ID

    client, factory = client_db
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    kunder = {row["slug"]: row["id"] for row in listed.json()}
    os_id = kunder[OS_DEFAULT_KUND_SLUG]

    async with factory() as db:
        admin = await db.get(UserAccount, ADMIN_USER_ID)
        assert admin is not None
        admin.kund_id = os_id
        await db.commit()

    os_expert = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": os_id,
            "name": "OS-expert underlag-kund",
            "occ": "Jurist",
            "district": "—",
            "quote": "Granskar text.",
        },
    )
    assert os_expert.status_code == 201, os_expert.text
    os_panel = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": "OS underlag-panel",
            "include_persona_ids": [os_expert.json()["id"]],
            "recipe": {"size": 1, "dist": {}},
        },
    )
    assert os_panel.status_code == 201, os_panel.text

    bolag_panel_id = await _create_expert_panel(client)

    uploaded = await client.post(
        "/underlag",
        params={"module": "expertgranskning"},
        files={"file": ("avtal.pdf", b"%PDF-1.4 underlag-kund-test", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    underlag_id = uploaded.json()["id"]

    denied = await client.post(
        "/expertgranskning/sessions",
        json={
            "document_text": "",
            "underlag_id": underlag_id,
            "panel_id": bolag_panel_id,
            "title": "Fel kund",
        },
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == "kund_access_denied"

    created = await client.post(
        "/expertgranskning/sessions",
        json={
            "document_text": "",
            "underlag_id": underlag_id,
            "panel_id": os_panel.json()["id"],
            "title": "Rätt kund",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["underlag_id"] == underlag_id

    async with factory() as db:
        admin = await db.get(UserAccount, ADMIN_USER_ID)
        assert admin is not None
        admin.kund_id = None
        await db.commit()


@pytest.mark.asyncio
async def test_expertgranskning_report_writes_source_pdf_creating_out_dir(
    client_db, tmp_path, monkeypatch
):
    """source.pdf must be writable even when report out_dir does not exist yet."""
    from types import SimpleNamespace

    from app.modules.report_binding import ReportGenerateContext
    from app.services.expertgranskning.module_report import (
        generate_expertgranskning_module_report,
    )
    from app.services.object_storage import KIND_UNDERLAG

    _client, factory = client_db
    out_dir = tmp_path / "rpt_pdf_underlag"
    assert not out_dir.exists()

    panel = SimpleNamespace(
        status="succeeded",
        result={"summary": "Ok"},
        config={
            "module": MODULE_ID,
            "brief": "Extraherad text",
            "review_intent": "",
            "underlag_id": "underlag-pdf-1",
            "topic": "PDF-test",
        },
        transcript=[],
        analysis="Ok",
        panel_id=1,
    )
    underlag = SimpleNamespace(
        kind=KIND_UNDERLAG,
        content_type="application/pdf",
    )

    async def _get_panel(_session, _session_id):
        return panel

    async def _get_stored(_session, _object_id):
        return underlag

    async def _read_bytes(_row):
        return b"%PDF-1.4 test-source", "application/pdf"

    monkeypatch.setattr(
        "app.services.expertgranskning.module_report.get_panel_session",
        _get_panel,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.module_report.is_expertgranskning_session",
        lambda _row: True,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.module_report.get_stored_object",
        _get_stored,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.module_report.read_stored_bytes",
        _read_bytes,
    )

    result = await generate_expertgranskning_module_report(
        ReportGenerateContext(
            report_id="rpt_pdf_underlag",
            title="PDF-test",
            locale="sv",
            sources=[{"type": SOURCE_TYPE, "session_id": "panel_x"}],
            mode=REPORT_MODE,
            out_dir=out_dir,
            session_factory=factory,
        )
    )
    source_pdf = out_dir / "source.pdf"
    assert source_pdf.is_file()
    assert source_pdf.read_bytes().startswith(b"%PDF")
    assert result.html_path.is_file()


@pytest.mark.asyncio
async def test_bolag_user_session_list_is_scoped(client: AsyncClient):
    from tests.conftest import BOLAG_USER_ID, mint_access_token

    panel_id = await _create_expert_panel(client)
    bolag_session = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "Bolag-text", "panel_id": panel_id, "title": "Bolag"},
    )
    assert bolag_session.status_code == 201

    os_draft = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "OS-text", "title": "OS-utkast"},
    )
    assert os_draft.status_code == 201
    os_id = os_draft.json()["id"]

    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=BOLAG_USER_ID, email='bolag@test.local')}"
    )
    listed = await client.get("/expertgranskning/sessions")
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()}
    assert bolag_session.json()["id"] in ids
    assert os_id not in ids


@pytest.mark.asyncio
async def test_bolag_user_can_watch_expertgranskning_panel_ws(client_db):
    from app.api.ws import _assert_panel_ws_access
    from app.database.models import UserAccount
    from tests.conftest import BOLAG_USER_ID

    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    client.headers["Authorization"] = (
        f"Bearer {__import__('tests.conftest', fromlist=['mint_access_token']).mint_access_token(sub=BOLAG_USER_ID, email='bolag@test.local')}"
    )
    created = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "WS-text", "panel_id": panel_id},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    async with factory() as session:
        bolag = await session.get(UserAccount, BOLAG_USER_ID)
        assert bolag is not None
        await _assert_panel_ws_access(
            session,
            bolag,
            session_id=session_id,
            campaign_id=None,
        )


@pytest.mark.asyncio
async def test_expertgranskning_report_rejects_unfinished_session(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    created = await client.post(
        "/expertgranskning/sessions",
        json={"document_text": "Utkast", "panel_id": panel_id},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]
    report = await client.post(
        "/reports",
        json={"sources": [{"type": SOURCE_TYPE, "session_id": session_id}]},
    )
    assert report.status_code == 400
    assert "has not succeeded" in report.json()["detail"]
