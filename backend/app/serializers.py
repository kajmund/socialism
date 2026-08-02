from __future__ import annotations

import re
import secrets
from datetime import UTC, date, datetime

from app.database.models import Persona, Population, PopulationMember, Run
from app.schemas.domain import (
    BranchState,
    EditablePersona,
    LibraryPersona,
    PersonaDetail,
    PopulationDetail,
    PopulationMemberOut,
    PopulationSummary,
    RunDetail,
    RunSummary,
    Tick,
    format_date,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def slug_id(name: str) -> str:
    parts = re.findall(r"[A-Za-zÅÄÖåäö]+", name)
    initials = "".join(p[0] for p in parts[:2]).lower()
    if len(initials) < 2:
        initials = (initials + "xx")[:2]
    return f"{initials}{secrets.token_hex(2)}"


def persona_initials(name: str) -> str:
    parts = name.split()
    return "".join(p[0] for p in parts[:2]).upper() if parts else "--"


def blank_profile(name: str = "Namnlös persona") -> EditablePersona:
    return EditablePersona(
        name=name,
        initials=persona_initials(name) if name != "Namnlös persona" else "--",
    )


def profile_from_dict(data: dict | None, fallback_name: str) -> EditablePersona:
    if not data:
        return blank_profile(fallback_name)
    return EditablePersona.model_validate({**blank_profile(fallback_name).model_dump(), **data})


def serialize_library_persona(persona: Persona, pops: list[str]) -> LibraryPersona:
    return LibraryPersona(
        id=persona.id,
        name=persona.name,
        age=persona.age,
        occ=persona.occ,
        district=persona.district,
        quote=persona.quote,
        pops=pops,
        updated=format_date(persona.updated_at),
        origin=persona.origin,  # type: ignore[arg-type]
    )


def serialize_persona_detail(persona: Persona, pops: list[str]) -> PersonaDetail:
    base = serialize_library_persona(persona, pops)
    return PersonaDetail(
        **base.model_dump(),
        profile=profile_from_dict(persona.profile, persona.name),
    )


def serialize_member(member: PopulationMember) -> PopulationMemberOut:
    return PopulationMemberOut(
        member_id=member.id,
        id=member.persona_id,
        name=member.name,
        initials=member.initials,
        age=member.age,
        occ=member.occ,
        district=member.district,
        trait=member.trait,
    )


def serialize_population_summary(population: Population, run_count: int) -> PopulationSummary:
    return PopulationSummary(
        id=population.id,
        name=population.name,
        size=population.size,
        runs=run_count,
        updated=format_date(population.updated_at),
        versions=population.versions,
        fp=population.fingerprint or [],
    )


def serialize_population_detail(
    population: Population,
    run_count: int,
    members: list[PopulationMember],
) -> PopulationDetail:
    summary = serialize_population_summary(population, run_count)
    return PopulationDetail(
        **summary.model_dump(),
        recipe=population.recipe or {},
        members=[serialize_member(m) for m in members],
    )


def tick_count(main_ticks: list | None, branch: dict | None) -> int:
    count = len(main_ticks or [])
    if branch:
        count += len(branch.get("a") or []) + len(branch.get("b") or [])
    return count


def variant_count(branch: dict | None) -> int:
    return 2 if branch else 1


def serialize_run_summary(run: Run, population_name: str) -> RunSummary:
    return RunSummary(
        id=run.id,
        name=run.name,
        status=run.status,  # type: ignore[arg-type]
        population=population_name,
        ticks=tick_count(run.main_ticks, run.branch),
        variants=variant_count(run.branch),
        seed=run.seed,
        updated=format_date(run.updated_at),
    )


def serialize_run_detail(run: Run, population_name: str) -> RunDetail:
    summary = serialize_run_summary(run, population_name)
    branch = None
    if run.branch:
        branch = BranchState.model_validate(run.branch)
    ticks = [Tick.model_validate(t) for t in (run.main_ticks or [])]
    start = run.start_date.isoformat() if run.start_date else None
    return RunDetail(
        **summary.model_dump(),
        population_id=run.population_id,
        start_date=start,
        main_ticks=ticks,
        branch=branch,
        results=run.results,
    )


def parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)
