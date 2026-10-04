"""Native provisioning failure and snapshot races leave no unused known resources."""

import pytest

from app.database.models import Persona
from app.services.elevenlabs_agents import ElevenLabsAgentsClient, ElevenLabsError, get_elevenlabs_client
from app.services.workspace_agent_deployment import deploy_agent_snapshot, prepare_agent_snapshot, save_agent_deployment
from tests.test_workspace_conversations import (
    provider as provider,
    single_connection_provider as single_connection_provider,
    probe_connection,
)


def failing_client(original, factory, workspace_id, *, stage, deleted):
    class Client(ElevenLabsAgentsClient):
        async def request(self, method, path, **kwargs):
            await probe_connection(factory, workspace_id)
            if method == "DELETE":
                assert kwargs.get("params") == ({"force": True} if "/tools/" in path else None)
                deleted.append(path)
                return {}
            config = kwargs.get("body", {}).get("tool_config", {})
            if ((stage == "tool" and config.get("name") == "get_job_status")
                    or (stage == "procedure" and path.endswith("/procedures"))
                    or (stage == "publish" and method == "PATCH")):
                raise ElevenLabsError("elevenlabs_request_failed")
            return await super().request(method, path, **kwargs)
    async def dependency():
        async for native in original():
            yield Client(native.http)
    return dependency


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["tool", "procedure", "publish"])
async def test_publish_failure_cleans_known_resources_without_db_connection(single_connection_provider, stage):
    fixture, _ = single_connection_provider
    client, factory, workspace_id, expert_id, requests = fixture
    app, deleted = client._transport.app, []
    original = app.dependency_overrides[get_elevenlabs_client]
    app.dependency_overrides[get_elevenlabs_client] = failing_client(original, factory, workspace_id, stage=stage, deleted=deleted)
    response = await client.post(f"/workspace-chat/{workspace_id}/sessions", json={"expert_id": expert_id, "mode": "text"})
    assert response.status_code == 502
    assert response.json() == {"detail": "elevenlabs_request_failed"}
    tool_names = [body["tool_config"]["name"] for method, path, body in requests
                  if method == "POST" and path == "/v1/convai/tools"]
    assert {path for path in deleted if "/tools/" in path} == {"/v1/convai/tools/tool-" + name for name in tool_names}
    if stage != "tool":
        assert deleted[0] == "/v1/convai/agents/agent-fixture"
    app.dependency_overrides[get_elevenlabs_client] = original


@pytest.mark.asyncio
async def test_raced_snapshot_uses_cached_winner_and_cleans_unused_copy(single_connection_provider, monkeypatch):
    from app.services import workspace_agent_deployment as deployment
    fixture, engine = single_connection_provider
    _, factory, workspace_id, expert_id, _ = fixture
    async with factory() as session:
        persona = await session.get(Persona, expert_id)
        snapshot = await prepare_agent_snapshot(session, persona=persona, language="sv", module="dd")
        await session.rollback()
    winner = {"agent_id": "winner", "agent_version": "published-winner", "tool_ids": {"read_source": "winner-tool"},
              "procedure_ids": {}}
    async with factory() as session:
        assert await save_agent_deployment(session, snapshot, winner) == winner
    loser = {**winner, "agent_id": "loser", "agent_version": "published-loser", "tool_ids": {"read_source": "loser-tool"}}
    async def published(*_args):
        return loser
    monkeypatch.setattr(deployment, "publish_agent_snapshot", published)
    deleted = []
    class Cleanup:
        async def request(self, method, path, **kwargs):
            assert engine.pool.checkedout() == 0
            await probe_connection(factory, workspace_id)
            assert kwargs.get("params") == ({"force": True} if "/tools/" in path else None)
            deleted.append((method, path))
            return {}
    async with factory() as session:
        chosen = await deploy_agent_snapshot(session, snapshot, Cleanup())
    assert chosen == winner
    assert deleted == [("DELETE", "/v1/convai/agents/loser"), ("DELETE", "/v1/convai/tools/loser-tool")]


@pytest.mark.asyncio
async def test_cleanup_failure_is_explicit_and_still_attempts_remaining_tools():
    from app.services.workspace_agent_deployment import cleanup_deployment
    attempted = []
    class Cleanup:
        async def request(self, _method, path, **kwargs):
            assert kwargs.get("params") == ({"force": True} if "/tools/" in path else None)
            attempted.append(path)
            if "/agents/" in path:
                raise ElevenLabsError("elevenlabs_request_failed")
            return {}
    with pytest.raises(ElevenLabsError, match="elevenlabs_publish_failed_cleanup_required"):
        await cleanup_deployment(Cleanup(), {"agent_id": "unused", "tool_ids": {"a": "ta", "b": "tb"}})
    assert attempted == ["/v1/convai/agents/unused", "/v1/convai/tools/ta", "/v1/convai/tools/tb"]
