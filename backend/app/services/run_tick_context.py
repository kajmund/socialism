"""Build persona feed context up through a tick for post-hoc interviews."""

from __future__ import annotations

from typing import Any

from app.services.oasis_run import _created_at_to_sort_key


def _agent_index_for_persona(variant: dict[str, Any], persona_id: str) -> int | None:
    for agent in variant.get("agents") or []:
        if agent.get("persona_id") == persona_id and agent.get("role") != "injector":
            idx = agent.get("index")
            if idx is not None:
                return int(idx)
    return None


def _name_for_user(agents: list[dict[str, Any]], user_id: int) -> str:
    for agent in agents:
        if agent.get("index") == user_id:
            return str(agent.get("member_name") or f"agent {user_id}")
    return f"agent {user_id}"


def _at_or_before(value: Any, cutoff: int) -> bool:
    key = _created_at_to_sort_key(value)
    if key is None:
        return False
    return key <= cutoff


def build_persona_feed_context(
    variant: dict[str, Any],
    *,
    persona_id: str,
    through_tick_index: int,
) -> tuple[str, dict[str, Any]]:
    """Return (context_text, tick_meta) for post-hoc interview prompts.

    Includes public posts/comments and the persona's own actions with
    created_at <= tick_markers[through_tick_index].time_end.
    """
    markers = list(variant.get("tick_markers") or [])
    if through_tick_index < 0 or through_tick_index >= len(markers):
        raise ValueError("through_tick_index out of range")

    marker = markers[through_tick_index]
    cutoff = int(marker["time_end"])
    day = int(marker.get("day") or through_tick_index + 1)
    agents = list(variant.get("agents") or [])
    agent_idx = _agent_index_for_persona(variant, persona_id)

    posts = [
        p
        for p in (variant.get("posts") or [])
        if _at_or_before(p.get("created_at"), cutoff)
    ]
    post_ids = {p.get("post_id") for p in posts}
    comments = [
        c
        for c in (variant.get("comments") or [])
        if c.get("post_id") in post_ids
        and (
            c.get("created_at") is None
            or _at_or_before(c.get("created_at"), cutoff)
        )
    ]
    comments_by_post: dict[Any, list[dict[str, Any]]] = {}
    for comment in comments:
        comments_by_post.setdefault(comment.get("post_id"), []).append(comment)

    lines: list[str] = [
        f"Tidpunkt: efter dag {day} (tick {through_tick_index + 1}).",
        "Du har inte sett något som hänt efter denna tidpunkt.",
        "",
        "=== Flöde du har sett ===",
    ]

    if not posts:
        lines.append("(Inga inlägg i flödet hittills.)")
    else:
        for post in sorted(
            posts,
            key=lambda p: (_created_at_to_sort_key(p.get("created_at")) or 0, p.get("post_id") or 0),
        ):
            uid = int(post.get("user_id") or -1)
            author = _name_for_user(agents, uid)
            content = (post.get("content") or "").strip()
            quote = (post.get("quote_content") or "").strip()
            body = f"{quote}\n{content}".strip() if quote else content
            lines.append(f"- [{author}] {body}")
            for comment in comments_by_post.get(post.get("post_id"), []):
                cuid = int(comment.get("user_id") or -1)
                cauthor = _name_for_user(agents, cuid)
                ctext = (comment.get("content") or "").strip()
                lines.append(f"  · kommentar från {cauthor}: {ctext}")

    if agent_idx is not None:
        own_actions: list[str] = []
        for row in variant.get("trace") or []:
            if int(row.get("user_id") or -1) != agent_idx:
                continue
            if not _at_or_before(row.get("created_at"), cutoff):
                continue
            action = (row.get("action") or "").strip()
            if not action or action in {"refresh", "sign_up", "do_nothing", "interview"}:
                continue
            own_actions.append(action.replace("_", " "))
        if own_actions:
            lines.append("")
            lines.append("=== Dina egna handlingar hittills ===")
            # Deduplicate while preserving order, cap length
            seen: set[str] = set()
            for action in own_actions:
                if action in seen:
                    continue
                seen.add(action)
                lines.append(f"- {action}")
                if len(seen) >= 20:
                    break

    meta = {
        "day": day,
        "tick_index": through_tick_index,
        "time_end": cutoff,
        "key": marker.get("key"),
        "agent_index": agent_idx,
    }
    return "\n".join(lines), meta
