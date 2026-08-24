"""In-process demo publisher for run-watch WebSocket UI testing."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Run
from app.database.session import SessionLocal
from app.realtime.run_broadcast import run_broadcast
from app.services.run_live_progress import append_live_progress_entry
from app.serializers import utcnow

DEMO_AGENTS = [
    {
        "index": 0,
        "username": "maria_h",
        "member_name": "Maria Holm",
        "persona_id": "mh",
        "role": "population",
    },
    {
        "index": 1,
        "username": "erik_l",
        "member_name": "Erik Lund",
        "persona_id": "el",
        "role": "population",
    },
    {
        "index": 99,
        "username": "s_partiet",
        "member_name": "Socialdemokraterna",
        "persona_id": None,
        "role": "injector",
    },
]

DEMO_ROUNDS = [
    {
        "tick_index": 0,
        "round_index": 0,
        "trace_start": 0,
        "trace_end": 2,
        "items": [
            {"user_id": 0, "action": "like_post", "post_id": 1, "created_at": 2},
            {"user_id": 1, "action": "refresh", "created_at": 3},
        ],
    },
    {
        "tick_index": 0,
        "round_index": 1,
        "trace_start": 2,
        "trace_end": 4,
        "items": [
            {
                "user_id": 1,
                "action": "create_comment",
                "post_id": 1,
                "comment_id": 1,
                "content": "Hoppas det märks i praktiken.",
                "created_at": 5,
            },
            {"user_id": 0, "action": "do_nothing", "created_at": 6},
        ],
    },
    {
        "tick_index": 1,
        "round_index": 0,
        "trace_start": 4,
        "trace_end": 6,
        "items": [
            {
                "user_id": 0,
                "action": "create_post",
                "post_id": 2,
                "content": "Bra att någon tar ansvar för äldreomsorgen i vår kommun.",
                "created_at": 8,
            },
            {"user_id": 1, "action": "like_post", "post_id": 2, "created_at": 9},
        ],
    },
]


async def publish_run_watch_demo(
    session: AsyncSession,
    *,
    run_id: int,
    variant_id: str,
    delay_seconds: float = 2.0,
    finish_run: bool = True,
) -> None:
    """Publish staged run-watch events through the running server's broadcast registry."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise ValueError(f"Run {run_id} not found")

    key = (run_id, variant_id)
    attempt_id = "att_demo_live"

    run.status = "running"
    run.updated_at = utcnow()
    await session.commit()

    await run_broadcast.publish(
        key,
        {"type": "run.attempt_started", "attempt_id": attempt_id},
    )
    await run_broadcast.publish(
        key,
        {
            "type": "run.attempt_started",
            "attempt_id": attempt_id,
            "agents": DEMO_AGENTS,
        },
    )

    seen_ticks: set[int] = set()
    for round_index, spec in enumerate(DEMO_ROUNDS):
        tick_index = int(spec["tick_index"])
        if tick_index not in seen_ticks:
            seen_ticks.add(tick_index)
            await run_broadcast.publish(
                key,
                {
                    "type": "tick.started",
                    "run_id": run_id,
                    "variant_id": variant_id,
                    "tick_index": tick_index,
                    "day": tick_index + 1,
                    "silent": False,
                    "key": f"t{tick_index + 1}",
                    "rounds": 2 if tick_index == 0 else 1,
                },
            )

        async with SessionLocal() as progress_session:
            await append_live_progress_entry(
                progress_session,
                run_id=run_id,
                variant_id=variant_id,
                entry={
                    "tick_index": spec["tick_index"],
                    "round_index": spec["round_index"],
                    "trace_start": spec["trace_start"],
                    "trace_end": spec["trace_end"],
                },
            )

        await run_broadcast.publish(
            key,
            {
                "type": "round.activity",
                "run_id": run_id,
                "variant_id": variant_id,
                "tick_index": spec["tick_index"],
                "round_index": spec["round_index"],
                "items": spec["items"],
            },
        )

        if delay_seconds > 0 and round_index < len(DEMO_ROUNDS) - 1:
            await asyncio.sleep(delay_seconds)

    for tick_index in sorted(seen_ticks):
        await run_broadcast.publish(
            key,
            {
                "type": "tick.completed",
                "run_id": run_id,
                "variant_id": variant_id,
                "tick_index": tick_index,
                "day": tick_index + 1,
                "silent": False,
                "key": f"t{tick_index + 1}",
                "rounds": 2 if tick_index == 0 else 1,
                "time_start": tick_index * 10,
                "time_end": tick_index * 10 + 9,
            },
        )

    await run_broadcast.publish(
        key,
        {
            "type": "run.attempt_finished",
            "run_id": run_id,
            "variant_id": variant_id,
            "attempt_id": attempt_id,
            "error": None,
        },
    )

    if finish_run:
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one()
        run.status = "done"
        run.updated_at = utcnow()
        await session.commit()
