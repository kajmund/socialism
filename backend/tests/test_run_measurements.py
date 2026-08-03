"""Unit tests for measurement aggregation from simulation feeds."""

from app.schemas.domain import Tick
from app.services.run_measurements import build_measurements


def _tick(key: str, day: int, measurements: list[str]) -> Tick:
    return Tick(
        key=key,
        day=day,
        silent=False,
        injections=[],
        rounds=1,
        measurements=measurements,
    )


def test_build_measurements_planned_when_no_feed():
    ticks = [
        _tick("t1", 1, ["opinion_snapshot"]),
        _tick("t2", 2, ["phrase_propagation", "engagement_decay"]),
    ]
    rows = build_measurements(ticks, ticks_run=0)
    assert len(rows) == 2
    assert rows[0]["day"] == 1
    assert rows[0]["points"][0]["id"] == "opinion_snapshot"
    assert rows[1]["points"][0]["id"] == "phrase_propagation"
    assert rows[0]["points"][0]["metrics"]["engagement"]["posts"] == 0


def test_build_measurements_splits_feed_and_districts():
    ticks = [
        _tick("t1", 1, ["opinion_snapshot"]),
        _tick("t2", 2, ["engagement_decay", "phrase_propagation"]),
    ]
    agents = [
        {
            "index": 0,
            "username": "a",
            "member_name": "Anna",
            "persona_id": "p1",
            "role": "population",
        },
        {
            "index": 1,
            "username": "b",
            "member_name": "Bo",
            "persona_id": "p2",
            "role": "population",
        },
    ]
    posts = [
        {
            "post_id": 1,
            "user_id": 0,
            "content": "Bra förslag på Vrinnevi sjukhuset",
            "num_likes": 3,
            "num_shares": 1,
        },
        {
            "post_id": 2,
            "user_id": 1,
            "content": "Dåligt beslut om skatten",
            "num_likes": 1,
            "num_shares": 0,
        },
        {
            "post_id": 3,
            "user_id": 0,
            "content": "Vrinnevi igen — hopp för äldreomsorg",
            "num_likes": 5,
            "num_shares": 2,
        },
        {
            "post_id": 4,
            "user_id": 1,
            "content": "Nej till förslaget",
            "num_likes": 0,
            "num_shares": 0,
        },
    ]
    comments = [
        {"comment_id": 1, "post_id": 1, "user_id": 1, "content": "Håller med", "num_likes": 1},
    ]
    rows = build_measurements(
        ticks,
        posts=posts,
        comments=comments,
        agents=agents,
        member_districts={"p1": "Hageby", "p2": "Lindö"},
        ticks_run=2,
    )
    assert len(rows) == 2
    snap = rows[0]["points"][0]
    assert snap["id"] == "opinion_snapshot"
    assert snap["metrics"]["engagement"]["posts"] >= 1
    districts = {d["label"] for d in snap["metrics"]["by_district"]}
    assert "Hageby" in districts or "Lindö" in districts

    decay = next(p for p in rows[1]["points"] if p["id"] == "engagement_decay")
    assert "engagement_delta" in decay["metrics"]

    phrases = next(p for p in rows[1]["points"] if p["id"] == "phrase_propagation")
    assert phrases["metrics"]["top_phrases"]
