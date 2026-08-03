"""Unit tests for OASIS run planning (no camel-oasis required)."""

from app.database.models import Run
from app.services.oasis_run import previous_attempts, variant_plans


def _tick(key: str, day: int, text: str = "") -> dict:
    inj = []
    if text:
        inj = [
            {
                "key": f"i-{key}",
                "type": "party_post",
                "sender": "@parti",
                "text": text,
                "mode": "text",
                "url": "",
                "fetching": False,
                "sourceDomain": "",
                "isVideo": False,
                "message_id": None,
            }
        ]
    return {
        "key": key,
        "day": day,
        "silent": False,
        "injections": inj,
        "rounds": 1,
        "measurements": [],
    }


def test_variant_plans_without_branch_uses_main_ticks():
    run = Run(
        id=1,
        name="x",
        status="draft",
        population_id=1,
        seed="s",
        main_ticks=[_tick("t1", 1, "hej"), _tick("t2", 2)],
        branch=None,
    )
    plans = variant_plans(run)
    assert len(plans) == 1
    vid, label, ticks = plans[0]
    assert vid == "main"
    assert label == "Huvudtidslinje"
    assert [t.key for t in ticks] == ["t1", "t2"]
    assert ticks[0].injections[0].text == "hej"


def test_variant_plans_with_branch_builds_stem_plus_a_and_b():
    run = Run(
        id=2,
        name="ab",
        status="draft",
        population_id=1,
        seed="s",
        main_ticks=[
            _tick("m1", 1, "gemensam"),
            _tick("m2", 2),
            _tick("m3-orphan", 3, "ska ignoreras"),
        ],
        branch={
            "afterIndex": 1,
            "a": [_tick("a3", 3, "version A")],
            "b": [_tick("b3", 3, "version B"), _tick("b4", 4)],
        },
    )
    plans = variant_plans(run)
    assert [p[0] for p in plans] == ["a", "b"]
    assert [p[1] for p in plans] == ["Version A", "Version B"]

    a_ticks = plans[0][2]
    b_ticks = plans[1][2]
    assert [t.key for t in a_ticks] == ["m1", "m2", "a3"]
    assert [t.key for t in b_ticks] == ["m1", "m2", "b3", "b4"]
    assert a_ticks[-1].injections[0].text == "version A"
    assert b_ticks[2].injections[0].text == "version B"
    assert "m3-orphan" not in [t.key for t in a_ticks + b_ticks]


def test_previous_attempts_normalizes_legacy_flat_results():
    legacy = {
        "engine": "oasis",
        "seed": "abc",
        "posts": [{"post_id": 1}],
        "comments": [],
        "agents": [],
        "ticks_run": 2,
    }
    attempts = previous_attempts(legacy)
    assert len(attempts) == 1
    assert attempts[0]["variants"][0]["posts"] == [{"post_id": 1}]
    assert attempts[0]["variants"][0]["id"] == "main"


def test_previous_attempts_keeps_attempts_list():
    stored = {
        "engine": "oasis",
        "attempts": [
            {"id": "att_new", "variants": [{"id": "a", "label": "A"}]},
            {"id": "att_old", "variants": [{"id": "main", "label": "H"}]},
        ],
    }
    attempts = previous_attempts(stored)
    assert [a["id"] for a in attempts] == ["att_new", "att_old"]


def test_remove_attempt_keeps_others_and_clears_last():
    from app.services.oasis_run import remove_attempt

    stored = {
        "engine": "oasis",
        "attempts": [
            {"id": "att_new", "variants": [{"id": "a", "label": "A"}]},
            {"id": "att_old", "variants": [{"id": "main", "label": "H"}]},
        ],
    }
    after = remove_attempt(stored, "att_new")
    assert after is not None
    assert [a["id"] for a in after["attempts"]] == ["att_old"]
    assert remove_attempt(after, "att_old") is None
