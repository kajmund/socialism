"""Shared JEV evaluation path: key, reuse, single-flight, then one outbound call.

Callers that have no security scope execute directly. They do not join another
tenant's in-flight call and they do not read or write artifacts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import settings
from app.jev.evaluation import (
    EVALUATION_STATUS_VALID,
    JEV_PROVIDER,
    EvaluationArtifact,
    EvaluationRequest,
    canonical_json,
    evaluation_key,
    sha256_text,
)
from app.jev.singleflight import SingleFlight
from app.jev.store import get_artifact, put_artifact, utc_now
from app.jev.system import (
    JevClientError,
    JevSystemOne,
    JevSystemOneResult,
    JevUsage,
    parse_noul,
)
from app.observability.research import record_jev_evaluation

logger = logging.getLogger(__name__)

_POOL_GRAPH = "graph_revalidation"
_POOL_GRAPH_HTTP = "graph_jev_http"
_POOL_JEV = "jev"


@dataclass(frozen=True)
class JevEvaluationBinding:
    session: AsyncSession
    security_scope: str


@dataclass(frozen=True)
class EvaluationOutcome:
    artifact: EvaluationArtifact | None
    error: JevClientError | None
    reused: bool
    joined: bool


_binding: ContextVar[JevEvaluationBinding | None] = ContextVar(
    "jev_evaluation_binding", default=None
)
_flights: dict[int, SingleFlight] = {}
_semaphores: dict[tuple[int, str], asyncio.Semaphore] = {}


def current_jev_binding() -> JevEvaluationBinding | None:
    return _binding.get()


@contextmanager
def jev_evaluation_binding(session: AsyncSession, security_scope: str):
    if not security_scope.strip():
        raise ValueError("JEV evaluation binding requires a security scope")
    token: Token[JevEvaluationBinding | None] = _binding.set(
        JevEvaluationBinding(session=session, security_scope=security_scope)
    )
    try:
        yield
    finally:
        _binding.reset(token)


def _flight() -> SingleFlight:
    loop_id = id(asyncio.get_running_loop())
    flight = _flights.get(loop_id)
    if flight is None:
        flight = SingleFlight()
        _flights[loop_id] = flight
    return flight


def background_jev_slots() -> int:
    """Graph revalidation may not occupy every outbound JEV slot.

    Foreground research (passage routing, structure, assessment) uses the
    same cap. Leaving one slot free when the cap is above 1 keeps a retrieval
    call from waiting behind a full batch of background evaluations.
    """
    cap = settings.jev_max_concurrency
    if cap <= 1:
        return cap
    return min(settings.graph_revalidation_max_concurrency, cap - 1)


def _pool_limit(pool: str) -> int:
    if pool == _POOL_JEV:
        return settings.jev_max_concurrency
    if pool == _POOL_GRAPH:
        return settings.graph_revalidation_max_concurrency
    if pool == _POOL_GRAPH_HTTP:
        return background_jev_slots()
    raise ValueError(f"unknown JEV concurrency pool: {pool}")


def _semaphore(pool: str) -> asyncio.Semaphore:
    key = (id(asyncio.get_running_loop()), pool)
    sem = _semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(_pool_limit(pool))
        _semaphores[key] = sem
    return sem


def build_request(
    *,
    evaluator_id: str,
    evaluator_version: str,
    model: str,
    questions: Mapping[str, Any],
    state: Mapping[str, Any],
    security_scope: str,
    content_hashes: Mapping[str, str] | None = None,
    policy_version: str,
    model_config: Mapping[str, Any] | None = None,
    domain_context_version: str | None = None,
) -> EvaluationRequest:
    hashes = dict(content_hashes or {})
    hashes.setdefault("state", sha256_text(canonical_json(dict(state))))
    return EvaluationRequest(
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
        model_provider=JEV_PROVIDER,
        model=model,
        model_config=dict(model_config or {}),
        questions=dict(questions),
        state=dict(state),
        content_hashes=hashes,
        policy_version=policy_version,
        security_scope=security_scope,
        domain_context_version=domain_context_version,
    )


async def evaluate_system_one(
    client: JevSystemOne,
    *,
    evaluator_id: str,
    evaluator_version: str,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    model: str,
    timeout_seconds: float,
    required_signals: Sequence[str],
    policy_version: str,
    security_scope: str | None = None,
    session: AsyncSession | None = None,
    content_hashes: Mapping[str, str] | None = None,
    model_config: Mapping[str, Any] | None = None,
    pool: str = _POOL_JEV,
) -> JevSystemOneResult:
    binding = current_jev_binding()
    scope = (
        security_scope
        if security_scope is not None
        else (binding.security_scope if binding is not None else None)
    )
    db = session if session is not None else (binding.session if binding is not None else None)
    if scope is None:
        return await _execute_unscoped(
            client,
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
            pool=pool,
        )
    request = build_request(
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
        model=model,
        questions=questions,
        state=state,
        security_scope=scope,
        content_hashes=content_hashes,
        policy_version=policy_version,
        model_config=model_config,
    )
    outcomes = await evaluate_many(
        client,
        [request],
        session=db,
        timeout_seconds=timeout_seconds,
        required_signals=required_signals,
        pool=pool,
    )
    outcome = outcomes[0]
    if outcome.error is not None:
        raise outcome.error
    if outcome.artifact is None:
        raise JevClientError("JEV evaluation produced no artifact", category="unknown")
    return _result_from_artifact(outcome.artifact, reused=outcome.reused)


async def evaluate_many(
    client: JevSystemOne,
    requests: Sequence[EvaluationRequest],
    *,
    session: AsyncSession | None,
    timeout_seconds: float,
    required_signals: Sequence[str],
    pool: str = _POOL_JEV,
    before_http: Callable[[], Awaitable[None]] | None = None,
) -> list[EvaluationOutcome]:
    """Lookup a copied artifact, release a read-only transaction, then HTTP.

    A miss is stored on a new session. That session re-reads the existing row
    before insert so a concurrent writer wins without the caller keeping the
    lookup session open across the call.
    """
    started = time.perf_counter()
    lookup_started = started
    prepared: list[_Prepared] = []
    for request in requests:
        record_jev_evaluation(requested=1)
        key = evaluation_key(request)
        artifact = None
        if session is not None:
            artifact = await get_artifact(
                session, evaluation_key=key, security_scope=request.security_scope
            )
        prepared.append(_Prepared(request=request, key=key, artifact=artifact))
    lookup_ms = (time.perf_counter() - lookup_started) * 1000
    if lookup_ms:
        record_jev_evaluation(cache_lookup_ms=lookup_ms)

    misses = [item for item in prepared if item.artifact is None]
    for item in prepared:
        if item.artifact is not None:
            _log_reused(item.request, item.key)
            record_jev_evaluation(reused=1)

    if misses:
        await _release_idle_transaction(session)
    if misses and before_http is not None:
        await before_http()

    if misses:
        computed = await asyncio.gather(
            *(_run_miss(client, item, timeout_seconds, required_signals, pool) for item in misses)
        )
        for item, outcome in zip(misses, computed, strict=True):
            item.computed = outcome

    persist_started = time.perf_counter()
    outcomes: list[EvaluationOutcome] = []
    pending: list[tuple[_Prepared, EvaluationArtifact, bool]] = []
    for item in prepared:
        if item.artifact is not None:
            outcomes.append(
                EvaluationOutcome(artifact=item.artifact, error=None, reused=True, joined=False)
            )
            continue
        computed = item.computed
        if computed is None:
            raise RuntimeError("JEV miss was not evaluated")
        if computed.error is not None or computed.artifact is None or session is None:
            outcomes.append(computed)
            continue
        pending.append((item, computed.artifact, computed.joined))
        outcomes.append(computed)
    if pending and session is not None:
        stored_by_key = await _persist_computed_artifacts(session, pending)
        replaced: list[EvaluationOutcome] = []
        for item, outcome in zip(prepared, outcomes, strict=True):
            stored = stored_by_key.get(item.key)
            if stored is None:
                replaced.append(outcome)
                continue
            artifact, joined = stored
            replaced.append(
                EvaluationOutcome(artifact=artifact, error=None, reused=False, joined=joined)
            )
        outcomes = replaced
    persist_ms = (time.perf_counter() - persist_started) * 1000
    if persist_ms and session is not None and misses:
        record_jev_evaluation(persistence_ms=persist_ms)
    return outcomes


def _artifact_session_maker(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    if not isinstance(bind, AsyncEngine):
        raise TypeError("JEV artifact persistence requires an engine-bound session")
    return async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)


async def _persist_computed_artifacts(
    session: AsyncSession,
    pending: Sequence[tuple[_Prepared, EvaluationArtifact, bool]],
) -> dict[str, tuple[EvaluationArtifact, bool]]:
    """Store misses on a new session and commit that session."""
    stored: dict[str, tuple[EvaluationArtifact, bool]] = {}
    async with _artifact_session_maker(session)() as persist_session:
        for item, artifact, joined in pending:
            stored[item.key] = (await put_artifact(persist_session, artifact), joined)
        await persist_session.commit()
    return stored


async def _release_idle_transaction(session: AsyncSession | None) -> None:
    """Return a read-only checkout before outbound HTTP.

    A transaction with pending writes stays open. The caller commits that
    work itself, as graph revalidation does in ``before_http``.
    """
    if session is None or not session.in_transaction():
        return
    if session.new or session.dirty or session.deleted:
        return
    await session.commit()


async def _run_miss(
    client: JevSystemOne,
    item: _Prepared,
    timeout_seconds: float,
    required_signals: Sequence[str],
    pool: str,
) -> EvaluationOutcome:
    try:
        artifact, joined = await _shared_http(
            client, item, timeout_seconds, required_signals, pool=pool
        )
    except JevClientError as exc:
        return EvaluationOutcome(artifact=None, error=exc, reused=False, joined=False)
    return EvaluationOutcome(artifact=artifact, error=None, reused=False, joined=joined)


async def _shared_http(
    client: JevSystemOne,
    item: _Prepared,
    timeout_seconds: float,
    required_signals: Sequence[str],
    *,
    pool: str = _POOL_JEV,
) -> tuple[EvaluationArtifact, bool]:
    wait_started = time.perf_counter()

    async def leader() -> EvaluationArtifact:
        # Joiners wait on the flight, not on a pool slot, so a second
        # discovery of the same key does not start another outbound call.
        if pool == _POOL_GRAPH:
            async with _semaphore(_POOL_GRAPH), _semaphore(_POOL_GRAPH_HTTP):
                return await _call_under_jev_cap()
        if pool != _POOL_JEV:
            async with _semaphore(pool):
                return await _call_under_jev_cap()
        return await _call_under_jev_cap()

    async def _call_under_jev_cap() -> EvaluationArtifact:
        async with _semaphore(_POOL_JEV):
            queue_ms = (time.perf_counter() - wait_started) * 1000
            record_jev_evaluation(queue_wait_ms=queue_ms)
            try:
                return await _call_and_validate(
                    client,
                    item.request,
                    item.key,
                    timeout_seconds=timeout_seconds,
                    required_signals=required_signals,
                )
            except JevClientError:
                record_jev_evaluation(failed=1)
                raise

    artifact, joined = await _flight().do(item.key, leader)
    if joined:
        record_jev_evaluation(
            singleflight_join=1,
            singleflight_wait_ms=(time.perf_counter() - wait_started) * 1000,
        )
    return artifact, joined


async def _call_and_validate(
    client: JevSystemOne,
    request: EvaluationRequest,
    key: str,
    *,
    timeout_seconds: float,
    required_signals: Sequence[str],
) -> EvaluationArtifact:
    http_started = time.perf_counter()
    try:
        result = await client.ask(
            state=dict(request.state),
            questions=dict(request.questions),
            model=request.model,
            timeout_seconds=timeout_seconds,
        )
    except JevClientError:
        record_jev_evaluation(
            executed=1,
            http_ms=(time.perf_counter() - http_started) * 1000,
            total_ms=(time.perf_counter() - http_started) * 1000,
        )
        raise
    parse_started = time.perf_counter()
    try:
        signals = {name: parse_noul(result.answers, name) for name in required_signals}
    except JevClientError:
        record_jev_evaluation(
            executed=1,
            http_ms=result.http_ms or ((time.perf_counter() - http_started) * 1000),
            parse_ms=(time.perf_counter() - parse_started) * 1000,
            total_ms=(time.perf_counter() - http_started) * 1000,
        )
        raise
    parse_ms = (time.perf_counter() - parse_started) * 1000 + result.parse_ms
    http_ms = result.http_ms or max((parse_started - http_started) * 1000, 0.0)
    record_jev_evaluation(
        executed=1,
        http_ms=http_ms,
        parse_ms=parse_ms,
        total_ms=http_ms + parse_ms,
    )
    return EvaluationArtifact(
        evaluation_key=key,
        security_scope=request.security_scope,
        result=dict(result.answers),
        signals=signals,
        evaluator_id=request.evaluator_id,
        evaluator_version=request.evaluator_version,
        model_provider=request.model_provider,
        model=result.model,
        input_provenance={
            "content_hashes": dict(request.content_hashes),
            "input_chars": result.input_chars,
            "state_sha256": request.content_hashes.get("state", ""),
            "http_ms": http_ms,
        },
        created_at=utc_now(),
        status=EVALUATION_STATUS_VALID,
    )


async def _execute_unscoped(
    client: JevSystemOne,
    *,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    model: str,
    timeout_seconds: float,
    pool: str,
) -> JevSystemOneResult:
    """No scope means no reuse and no join. The outbound cap still applies."""
    record_jev_evaluation(requested=1)
    if pool != _POOL_JEV:
        async with _semaphore(pool):
            return await _unscoped_call(
                client,
                state=state,
                questions=questions,
                model=model,
                timeout_seconds=timeout_seconds,
            )
    return await _unscoped_call(
        client, state=state, questions=questions, model=model, timeout_seconds=timeout_seconds
    )


async def _unscoped_call(
    client: JevSystemOne,
    *,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    model: str,
    timeout_seconds: float,
) -> JevSystemOneResult:
    queued = time.perf_counter()
    async with _semaphore(_POOL_JEV):
        record_jev_evaluation(queue_wait_ms=(time.perf_counter() - queued) * 1000)
        started = time.perf_counter()
        try:
            result = await client.ask(
                state=state,
                questions=dict(questions),
                model=model,
                timeout_seconds=timeout_seconds,
            )
        except JevClientError:
            record_jev_evaluation(
                executed=1,
                failed=1,
                http_ms=(time.perf_counter() - started) * 1000,
            )
            raise
    record_jev_evaluation(
        executed=1,
        http_ms=result.http_ms or ((time.perf_counter() - started) * 1000),
        parse_ms=result.parse_ms,
    )
    return result


def _result_from_artifact(artifact: EvaluationArtifact, *, reused: bool) -> JevSystemOneResult:
    provenance = artifact.input_provenance
    input_chars = provenance.get("input_chars")
    http_ms = provenance.get("http_ms")
    latency_ms = 0.0 if reused else float(http_ms) if isinstance(http_ms, (int, float)) else 0.0
    return JevSystemOneResult(
        answers=dict(artifact.result),
        model=artifact.model,
        latency_ms=latency_ms,
        input_chars=int(input_chars) if isinstance(input_chars, int) else 0,
        usage=JevUsage(),
        raw={"evaluation_key": artifact.evaluation_key, "reused": reused},
    )


def _log_reused(request: EvaluationRequest, key: str) -> None:
    logger.info(
        "jev_evaluation_reused evaluator_id=%s evaluator_version=%s model=%s "
        "security_scope=%s evaluation_key=%s",
        request.evaluator_id,
        request.evaluator_version,
        request.model,
        request.security_scope,
        key,
    )


class _Prepared:
    def __init__(
        self,
        *,
        request: EvaluationRequest,
        key: str,
        artifact: EvaluationArtifact | None,
    ) -> None:
        self.request = request
        self.key = key
        self.artifact = artifact
        self.computed: EvaluationOutcome | None = None
