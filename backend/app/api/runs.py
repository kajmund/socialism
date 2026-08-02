import secrets
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Message, Population, Run
from app.database.session import get_session
from app.schemas.domain import (
    RunCreate,
    RunDetail,
    RunPopulationOption,
    RunSummary,
    RunUpdate,
)
from app.serializers import (
    parse_optional_date,
    serialize_run_detail,
    serialize_run_summary,
    utcnow,
)
from app.services.oasis_run import OasisUnavailable, oasis_installed, simulate_run

router = APIRouter(prefix="/runs", tags=["runs"])


async def _get_run(session: AsyncSession, run_id: int) -> Run:
    result = await session.execute(
        select(Run).options(selectinload(Run.population)).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _ticks_payload(ticks: list) -> list:
    return [t.model_dump() if hasattr(t, "model_dump") else t for t in ticks]


def _branch_payload(branch) -> dict | None:
    if branch is None:
        return None
    return branch.model_dump() if hasattr(branch, "model_dump") else branch


async def _snapshot_message_bodies(session: AsyncSession, run: Run) -> None:
    """Freeze library Message.body into Injection.text before a run starts."""

    def collect_ids(ticks: list[Any]) -> set[str]:
        ids: set[str] = set()
        for tick in ticks or []:
            for inj in (tick.get("injections") if isinstance(tick, dict) else []) or []:
                mid = inj.get("message_id") if isinstance(inj, dict) else None
                if mid:
                    ids.add(mid)
        return ids

    message_ids = collect_ids(run.main_ticks or [])
    branch = run.branch or {}
    if isinstance(branch, dict):
        message_ids |= collect_ids(branch.get("a") or [])
        message_ids |= collect_ids(branch.get("b") or [])

    if not message_ids:
        return

    result = await session.execute(select(Message).where(Message.id.in_(message_ids)))
    by_id = {m.id: m for m in result.scalars().all()}
    missing = sorted(message_ids - set(by_id))
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Referenced messages not found: {', '.join(missing)}",
        )

    def apply(ticks: list[Any]) -> list[Any]:
        out = deepcopy(ticks or [])
        for tick in out:
            if not isinstance(tick, dict):
                continue
            for inj in tick.get("injections") or []:
                if not isinstance(inj, dict):
                    continue
                mid = inj.get("message_id")
                if mid and mid in by_id:
                    inj["text"] = by_id[mid].body
        return out

    run.main_ticks = apply(run.main_ticks or [])
    if isinstance(branch, dict) and branch:
        run.branch = {
            **branch,
            "a": apply(branch.get("a") or []),
            "b": apply(branch.get("b") or []),
        }


@router.get("", response_model=list[RunSummary])
async def list_runs(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[RunSummary]:
    stmt = select(Run).options(selectinload(Run.population)).order_by(Run.updated_at.desc())
    if status:
        stmt = stmt.where(Run.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Run.name.ilike(like))
    result = await session.execute(stmt)
    runs = list(result.scalars().all())
    return [serialize_run_summary(run, run.population.name) for run in runs]


@router.get("/populations", response_model=list[RunPopulationOption])
async def list_run_populations(
    session: AsyncSession = Depends(get_session),
) -> list[RunPopulationOption]:
    result = await session.execute(
        select(Population)
        .options(selectinload(Population.members))
        .order_by(Population.name)
    )
    populations = list(result.scalars().all())
    out: list[RunPopulationOption] = []
    for population in populations:
        initials = [m.initials for m in population.members[:3]]
        out.append(
            RunPopulationOption(
                id=population.id,
                name=population.name,
                size=population.size,
                initials=initials,
            )
        )
    return out


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    run = await _get_run(session, run_id)
    return serialize_run_detail(run, run.population.name)


@router.post("", response_model=RunDetail, status_code=201)
async def create_run(
    body: RunCreate,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    population = await session.get(Population, body.population_id)
    if population is None:
        raise HTTPException(status_code=404, detail="Population not found")
    run = Run(
        name=body.name,
        status=body.status,
        population_id=body.population_id,
        seed=body.seed or secrets.token_hex(4),
        start_date=parse_optional_date(body.start_date),
        main_ticks=_ticks_payload(body.main_ticks),
        branch=_branch_payload(body.branch),
        updated_at=utcnow(),
    )
    session.add(run)
    await session.commit()
    run = await _get_run(session, run.id)
    return serialize_run_detail(run, run.population.name)


@router.put("/{run_id}", response_model=RunDetail)
async def update_run(
    run_id: int,
    body: RunUpdate,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    run = await _get_run(session, run_id)
    data = body.model_dump(exclude_unset=True)
    if "population_id" in data:
        population = await session.get(Population, data["population_id"])
        if population is None:
            raise HTTPException(status_code=404, detail="Population not found")
    if "start_date" in data:
        data["start_date"] = parse_optional_date(data["start_date"])
    if "main_ticks" in data and data["main_ticks"] is not None:
        data["main_ticks"] = _ticks_payload(data["main_ticks"])
    if "branch" in data and data["branch"] is not None:
        data["branch"] = _branch_payload(data["branch"])
    for key, value in data.items():
        setattr(run, key, value)
    run.updated_at = utcnow()
    await session.commit()
    run = await _get_run(session, run_id)
    return serialize_run_detail(run, run.population.name)


@router.post("/{run_id}/start", response_model=RunDetail)
async def start_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    run = await _get_run(session, run_id)
    if run.status == "done":
        raise HTTPException(status_code=409, detail="Run already completed")

    await _snapshot_message_bodies(session, run)

    if settings.simulation_engine != "oasis":
        run.status = "running"
        run.updated_at = utcnow()
        await session.commit()
        run = await _get_run(session, run_id)
        return serialize_run_detail(run, run.population.name)

    if not settings.deepseek_api_key:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY is required when SIMULATION_ENGINE=oasis",
        )
    if not oasis_installed():
        raise HTTPException(
            status_code=503,
            detail="camel-oasis is not installed. Run: uv sync --extra oasis",
        )

    run.status = "running"
    run.results = None
    run.updated_at = utcnow()
    await session.commit()

    try:
        results = await simulate_run(session, run)
        run.status = "done"
        run.results = results
    except OasisUnavailable as exc:
        run.status = "failed"
        run.results = {"engine": "oasis", "error": str(exc)}
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — mark run failed for any OASIS/LLM error
        run.status = "failed"
        run.results = {"engine": "oasis", "error": str(exc)}
        run.updated_at = utcnow()
        await session.commit()
        run = await _get_run(session, run_id)
        return serialize_run_detail(run, run.population.name)

    run.updated_at = utcnow()
    await session.commit()
    run = await _get_run(session, run_id)
    return serialize_run_detail(run, run.population.name)


@router.post("/{run_id}/duplicate", response_model=RunDetail, status_code=201)
async def duplicate_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    source = await _get_run(session, run_id)
    run = Run(
        name=f"{source.name} (kopia)",
        status="draft",
        population_id=source.population_id,
        seed=secrets.token_hex(4),
        start_date=source.start_date,
        main_ticks=list(source.main_ticks or []),
        branch=dict(source.branch) if source.branch else None,
        updated_at=utcnow(),
    )
    session.add(run)
    await session.commit()
    run = await _get_run(session, run.id)
    return serialize_run_detail(run, run.population.name)


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    run = await _get_run(session, run_id)
    await session.delete(run)
    await session.commit()
