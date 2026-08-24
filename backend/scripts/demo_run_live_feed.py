"""Publish demo run-watch events for UI testing without a full OASIS run."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select

from app.database.models import Run
from app.database.session import SessionLocal
from app.realtime.run_broadcast import run_broadcast
from app.services.run_live_progress import append_live_progress_entry


async def _publish_demo(*, run_id: int, variant_id: str, delay: float) -> None:
    key = (run_id, variant_id)
    attempt_id = "att_demo_live"

    await run_broadcast.publish(
        key,
        {"type": "run.attempt_started", "attempt_id": attempt_id},
    )
    await run_broadcast.publish(
        key,
        {
            "type": "run.attempt_started",
            "attempt_id": attempt_id,
            "agents": [
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
            ],
        },
    )

    rounds = [
        {
            "tick_index": 0,
            "round_index": 0,
            "trace_start": 0,
            "trace_end": 2,
            "items": [
                {
                    "user_id": 0,
                    "action": "like_post",
                    "post_id": 1,
                    "created_at": 2,
                },
                {
                    "user_id": 1,
                    "action": "refresh",
                    "created_at": 3,
                },
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
                {
                    "user_id": 0,
                    "action": "do_nothing",
                    "created_at": 6,
                },
            ],
        },
    ]

    async with SessionLocal() as session:
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise SystemExit(f"Run {run_id} not found")
        run.status = "running"
        await session.commit()

    for round_index, spec in enumerate(rounds):
        await run_broadcast.publish(
            key,
            {
                "type": "tick.started",
                "run_id": run_id,
                "variant_id": variant_id,
                "tick_index": spec["tick_index"],
                "day": 1,
                "silent": False,
                "key": "t1",
                "rounds": 2,
            },
        )
        async with SessionLocal() as session:
            await append_live_progress_entry(
                session,
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
        if delay > 0 and round_index < len(rounds) - 1:
            await asyncio.sleep(delay)

    await run_broadcast.publish(
        key,
        {
            "type": "tick.completed",
            "run_id": run_id,
            "variant_id": variant_id,
            "tick_index": 0,
            "day": 1,
            "silent": False,
            "key": "t1",
            "rounds": 2,
            "time_start": 0,
            "time_end": 10,
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

    async with SessionLocal() as session:
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one()
        run.status = "done"
        await session.commit()

    print(f"Published demo live feed for run {run_id} variant {variant_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo run-watch WebSocket events")
    parser.add_argument("--run-id", type=int, default=1)
    parser.add_argument("--variant-id", default="a")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between rounds")
    args = parser.parse_args()
    asyncio.run(
        _publish_demo(
            run_id=args.run_id,
            variant_id=args.variant_id,
            delay=args.delay,
        )
    )


if __name__ == "__main__":
    main()
