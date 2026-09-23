"""TypeSafe System One error categories and usage parsing."""

from __future__ import annotations

import httpx
import pytest

from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    classify_jev_error,
    parse_usage,
)


def test_classify_timeout_and_unknown():
    assert classify_jev_error(httpx.TimeoutException("slow")) == "timeout"
    assert classify_jev_error(RuntimeError("boom")) == "unknown"
    assert classify_jev_error(JevClientError("nope", category="rate_limit")) == "rate_limit"


def test_parse_usage_aliases():
    usage = parse_usage({"usage": {"input_tokens": 9, "output_tokens": 3}})
    assert usage.prompt_tokens == 9
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 12


@pytest.mark.asyncio
async def test_http_status_categories(monkeypatch):
    monkeypatch.setattr("app.jev.system.settings.typesafe_api_key", "k")
    monkeypatch.setattr(
        "app.jev.system.settings.typesafe_base_url", "https://jev.example.test"
    )

    async def expect(status: int, category: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(status, text="nope")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = HttpJevSystemOne(http)
            with pytest.raises(JevClientError) as exc:
                await client.ask(
                    state={"q": "x"},
                    questions={"a": {"type": "noul", "instructions": "y"}},
                    model="jev-1.12",
                    timeout_seconds=1,
                )
            assert exc.value.category == category

    await expect(401, "auth")
    await expect(429, "rate_limit")
    await expect(503, "transport")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), "NaN"])
def test_noul_rejects_nonfinite_probabilities(value):
    from app.jev.system import parse_noul
    with pytest.raises(JevClientError) as error:
        parse_noul({"answer": {"noul": value}}, "answer")
    assert error.value.category == "schema_validation"


@pytest.mark.asyncio
async def test_client_reports_invalid_model_and_applies_injected_timeout(monkeypatch):
    monkeypatch.setattr("app.jev.system.settings.typesafe_api_key", "test")
    def handler(request):
        assert request.extensions["timeout"]["read"] == 0.25
        return httpx.Response(400, json={"detail": {"message": "Unknown model"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(JevClientError) as error:
            await HttpJevSystemOne(http).ask(
                state={}, questions={}, model="invalid", timeout_seconds=0.25,
            )
    assert error.value.category == "invalid_request"
