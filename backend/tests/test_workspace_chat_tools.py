"""Expert text chat receives the workspace selection and workspace tools."""

from app.schemas.workspace import WorkspaceState
from app.services.expert_async_tools import (
    LibraryToolScope,
    PlannedCall,
    ToolWork,
)
from app.services.expert_workspace_tool_run import run_workspace_tool_call
from app.services.expert_tool_followup import queue_document_open
from app.services.workspace_chat_tools import workspace_openai_tools, workspace_turn_text


def test_turn_text_includes_the_selected_quote():
    prompts = {
        "workspace.chat.turn": "Läge:\n{workspace_json}",
    }
    state = WorkspaceState(
        selection={
            "source_id": "source-1",
            "anchor": {"exact_text": "Löpande räkning", "page_number": 2},
        }
    )
    text = workspace_turn_text(prompts, state)
    assert "Löpande räkning" in text
    assert "source-1" in text


def test_workspace_tools_include_selection_and_display():
    prompts = {f"workspace.voice.tool.{name}": name for name in (
        "get_workspace_context", "show_document", "focus_anchor", "search_knowledge",
        "read_source", "ingest_source", "get_job_status", "compare_sources", "get_relations",
        "render_chart", "create_document", "revise_document", "export_document", "start_research",
        "open_ingest_picker", "show_evidence", "show_comparison", "show_relations", "show_knowledge",
        "show_artifact",
    )}
    names = {spec["function"]["name"] for spec in workspace_openai_tools(prompts)}
    assert {"get_workspace_context", "show_document", "focus_anchor", "search_knowledge"} <= names
    skipped = {spec["function"]["name"] for spec in workspace_openai_tools(prompts, skip=frozenset({"start_research"}))}
    assert "start_research" not in skipped


def test_display_tools_stay_on_the_client():
    scope = LibraryToolScope(
        enabled=True,
        persona_id="exp",
        mode="interview",
        actor_user_id="user",
        history=[],
        user_message="hej",
        workspace=("ws", {}),
    )
    scope.defer([
        PlannedCall("1", "focus_anchor", {"reference_id": "ref"}),
        PlannedCall("2", "search_knowledge", {"query": "ersättning"}),
    ])
    assert [call.name for call in scope.client_calls] == ["focus_anchor"]
    assert [call.name for call in scope._calls] == ["search_knowledge"]
    queue_document_open(scope, "contract")
    assert scope.client_calls[-1].name == "show_document"
    assert scope.client_calls[-1].arguments == {"source_id": "contract"}
    assert scope._calls == []


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, _model, user_id):
        return type("User", (), {"id": user_id})()

    def expunge(self, _user):
        return None

    async def rollback(self):
        return None

    async def commit(self):
        return None


async def test_queued_workspace_job_starts_after_commit(monkeypatch):
    scheduled: list[str] = []

    async def execute(*_args, **_kwargs):
        return {"status": "queued", "job_id": "job_draft", "artifact_id": "art"}

    monkeypatch.setattr("app.services.expert_workspace_tool_run.job_session_factory", lambda: _Session)
    monkeypatch.setattr("app.services.workspace.tools.execute_workspace_tool", execute)
    monkeypatch.setattr("app.services.expert_workspace_tool_run.enqueue_job", scheduled.append)
    text = await run_workspace_tool_call(
        PlannedCall("call-1", "create_document", {"title": "Sammanfattning"}),
        ToolWork(
            persona_id="exp",
            mode="interview",
            actor_user_id="user",
            history=[],
            user_message="sammanfatta",
            calls=(),
            workspace_id="ws",
            workspace_state={},
        ),
    )
    assert scheduled == ["job_draft"]
    assert "job_draft" in text
