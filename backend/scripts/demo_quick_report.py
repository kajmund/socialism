"""Generate a demo snabbrapport HTML for local preview (no API keys)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.llm import set_structured_completer
from app.schemas.domain import Tick
from app.services.prompt_catalog import default_prompts
from app.services.report.bundles import RunBundle
from app.services.report.generate import generate_report_html
from app.services.run_measurements import build_measurements
from app.services.ssr import set_embedder


async def _fake_embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for t in texts:
        v = [0.0] * 8
        v[hash(t) % 8] = 1.0
        v[(hash(t) // 8) % 8] = 0.5
        out.append(v)
    return out


def _ab_bundles() -> list[RunBundle]:
    injection = (
        "Socialdemokraterna vill stoppa nedsläckningen av vägbelysning "
        "i byar. Belysningen är avgörande för tryggheten."
    )
    agents = [
        {"index": 0, "member_name": "Partikonto", "role": "injector"},
        {"index": 1, "member_name": "Anna Lind", "role": "population"},
        {"index": 2, "member_name": "Bo Nilsson", "role": "population"},
        {"index": 3, "member_name": "Cecilia Ek", "role": "population"},
        {"index": 4, "member_name": "David Holm", "role": "population"},
        {"index": 5, "member_name": "Eva Strand", "role": "population"},
    ]
    base = dict(
        run_id=42,
        run_name="Demo — belysning A/B",
        attempt_id="demo_att",
        seed="demo",
        engine="oasis",
        agents=agents,
        ticks_run=3,
        injection_texts=[injection],
        follows=[
            {"follower_id": 2, "followee_id": 1},
            {"follower_id": 3, "followee_id": 1},
            {"follower_id": 4, "followee_id": 2},
        ],
        action_histogram=[
            {"action": "like_post", "count": 18},
            {"action": "comment_post", "count": 9},
            {"action": "follow", "count": 3},
        ],
    )
    raw = [
        RunBundle(
            label="Demo — belysning A/B — Version A",
            variant_id="a",
            tick_markers=[
                {"tick_index": 0, "day": 1, "silent": False, "key": "d1", "rounds": 3, "time_start": 0, "time_end": 4},
                {"tick_index": 1, "day": 2, "silent": False, "key": "d2", "rounds": 3, "time_start": 5, "time_end": 9},
                {"tick_index": 2, "day": 3, "silent": True, "key": "d3", "rounds": 2, "time_start": 10, "time_end": 14},
            ],
            trace=[
                {
                    "user_id": 2,
                    "created_at": 6,
                    "action": "interview",
                    "info": '{"prompt": "Vad tycker du om förslaget om belysning?", "response": "Bra och konkret — känns tryggt för oss på landsbygden."}',
                },
            ],
            posts=[
                {
                    "post_id": 1,
                    "user_id": 0,
                    "content": injection,
                    "num_likes": 12,
                    "num_shares": 2,
                    "num_dislikes": 1,
                    "created_at": 1,
                },
                {
                    "post_id": 2,
                    "user_id": 1,
                    "content": "Bra förslag — trygghet på landsbygden kräver belysning.",
                    "num_likes": 6,
                    "num_shares": 1,
                    "created_at": 3,
                },
                {
                    "post_id": 3,
                    "user_id": 3,
                    "content": "Enligt rapporten behövs mer data om trygghet i mörker.",
                    "num_likes": 3,
                    "created_at": 7,
                },
            ],
            comments=[
                {
                    "comment_id": 1,
                    "post_id": 1,
                    "user_id": 2,
                    "content": "Äntligen någon som tar landsbygdens trygghet på allvar!",
                    "num_likes": 4,
                    "created_at": 2,
                },
                {
                    "comment_id": 2,
                    "post_id": 1,
                    "user_id": 4,
                    "content": "Konkret och bra — hoppas det blir av.",
                    "num_likes": 2,
                    "created_at": 4,
                },
                {
                    "comment_id": 3,
                    "post_id": 2,
                    "user_id": 5,
                    "content": "Håller med, belysning gör skillnad varje kväll.",
                    "num_likes": 1,
                    "created_at": 8,
                },
            ],
            **base,
        ),
        RunBundle(
            label="Demo — belysning A/B — Version B",
            variant_id="b",
            posts=[
                {
                    "post_id": 10,
                    "user_id": 0,
                    "content": injection.replace("stoppa", "pausa"),
                    "num_likes": 5,
                    "num_shares": 0,
                    "num_dislikes": 3,
                },
                {
                    "post_id": 11,
                    "user_id": 2,
                    "content": "Uselt förslag — bara valfläsk inför valet.",
                    "num_likes": 2,
                },
                {
                    "post_id": 12,
                    "user_id": 4,
                    "content": "Skandal att man prioriterar detta när skolan brister.",
                    "num_likes": 1,
                    "num_dislikes": 1,
                },
            ],
            comments=[
                {
                    "comment_id": 10,
                    "post_id": 10,
                    "user_id": 3,
                    "content": "Typiskt tomma löften utan finansiering.",
                    "num_likes": 3,
                },
                {
                    "comment_id": 11,
                    "post_id": 10,
                    "user_id": 5,
                    "content": "Inte alls imponerad — retorik utan substans.",
                    "num_likes": 1,
                },
            ],
            follows=[{"follower_id": 3, "followee_id": 2}],
            action_histogram=[
                {"action": "like_post", "count": 8},
                {"action": "comment_post", "count": 5},
                {"action": "dislike_post", "count": 2},
            ],
            **{k: v for k, v in base.items() if k not in ("follows", "action_histogram")},
        ),
    ]
    ticks = [
        Tick(key="d1", day=1, measurements=["opinion_snapshot"]),
        Tick(key="d2", day=2, measurements=["engagement_decay"]),
        Tick(key="d3", day=3, silent=True, measurements=["phrase_propagation"]),
    ]
    out: list[RunBundle] = []
    for bundle in raw:
        bundle.measurements = build_measurements(
            ticks,
            posts=bundle.posts,
            comments=bundle.comments,
            agents=bundle.agents,
            follows=bundle.follows,
            ticks_run=bundle.ticks_run,
        )
        out.append(bundle)
    return out


async def main() -> None:
    out_dir = Path("/opt/cursor/artifacts/demo-snabbrapport")
    out_dir.mkdir(parents=True, exist_ok=True)

    async def _no_llm(_messages, _model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(_no_llm)
    set_embedder(_fake_embed)
    try:
        html_path, _, _, _ = await generate_report_html(
            _ab_bundles(),
            out_dir=out_dir,
            dry_run=False,
            title="Demo snabbrapport — belysning A/B",
            mode="quick",
            prompts=default_prompts("sv"),
            locale="sv",
        )
        print(html_path)
    finally:
        set_structured_completer(None)
        set_embedder(None)


if __name__ == "__main__":
    asyncio.run(main())
