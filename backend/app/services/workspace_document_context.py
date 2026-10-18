"""Document text the voice agent can answer from in the same turn."""

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.stored_objects import StoredObject
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact
from app.schemas.workspace import WorkspaceState
from app.services.workspace_parent_documents import voice_document_inventory
_OPEN_REQUEST = re.compile(r"(?i)(?<!\w)(?:öppna|visa|open|show)(?!\w)")
_TERM = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_STOP_TERMS = frozenset({
    "öppna", "visa", "open", "show", "avtal", "avtalet", "dokument", "dokumentet",
    "filen", "filer", "kunden", "kund", "underlag", "arbetsytan", "detta", "denna",
    "bara", "inte", "finns", "öppet",
})


def select_excerpt_ids(inventory: list[dict], open_ids: list[str]) -> list[str]:
    """Source ids of tabs that are actually open. Nothing else is named in the turn."""
    known = {row["source_object_id"] for row in inventory}
    return [source_id for source_id in open_ids if source_id in known]


def open_artifact_ids(state: WorkspaceState) -> set[str]:
    """Artifact tabs, including the active one when it is missing from the tab list."""
    ids = set(state.open_artifact_ids)
    if state.active_artifact_id:
        ids.add(state.active_artifact_id)
    return ids


def distinctive_terms(text: str) -> list[str]:
    terms: list[str] = []
    for word in _TERM.findall(text):
        term = word.casefold()
        if term in _STOP_TERMS or term in terms:
            continue
        terms.append(term)
    return terms


def open_request_terms(message: str, earlier_user_messages: list[str]) -> list[str] | None:
    if _OPEN_REQUEST.search(message) is None:
        return None
    own = distinctive_terms(message)
    if own:
        return own
    for earlier in reversed(earlier_user_messages):
        terms = distinctive_terms(earlier)
        if terms:
            return terms
    return []


def matching_source_id(
    inventory: list[dict],
    texts: dict[str, str],
    terms: list[str],
    assistant_text: str,
) -> str | None:
    with_text = [row for row in inventory if texts.get(row["source_object_id"], "").strip()]
    if terms:
        hits = [row["source_object_id"] for row in with_text if _contains_all(row, texts, terms)]
        return hits[0] if len(hits) == 1 else None
    folded = assistant_text.casefold()
    named = [
        row["source_object_id"]
        for row in inventory
        if row.get("filename") and str(row["filename"]).casefold() in folded
    ]
    if len(set(named)) == 1:
        return named[0]
    agreements = [
        row["source_object_id"]
        for row in inventory
        if "avtal" in str(row.get("filename") or "").casefold()
    ]
    if len(set(agreements)) == 1:
        return agreements[0]
    return with_text[0]["source_object_id"] if len(with_text) == 1 else None


_NODE_KIND = {
    "event": "händelse",
    "condition": "villkor",
    "effect": "effekt",
    "interpretation": "tolkning",
}
_READABLE_KINDS = ("document", "relations")


def artifact_plain_text(content: object) -> str:
    if not isinstance(content, dict):
        return ""
    blocks = content.get("blocks")
    if not isinstance(blocks, list):
        return ""
    parts = [
        str(block.get("text") or "").strip()
        for block in blocks
        if isinstance(block, dict) and str(block.get("text") or "").strip()
    ]
    return "\n\n".join(parts)


def relation_plain_text(content: object) -> str:
    """Nodes and edges an expert can read without the graph on screen."""
    if not isinstance(content, dict):
        return ""
    nodes = content.get("nodes") if isinstance(content.get("nodes"), list) else []
    edges = content.get("edges") if isinstance(content.get("edges"), list) else []
    labels: dict[str, str] = {}
    node_lines = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        label = str(node.get("label") or "").strip() or node_id
        if node_id:
            labels[node_id] = label
        kind = _NODE_KIND.get(str(node.get("kind") or ""), str(node.get("kind") or ""))
        line = f"- {label} ({kind})" if kind else f"- {label}"
        line += _source_refs(node.get("source_refs"))
        node_lines.append(line)
    edge_lines = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = labels.get(str(edge.get("source") or ""), str(edge.get("source") or ""))
        target = labels.get(str(edge.get("target") or ""), str(edge.get("target") or ""))
        label = str(edge.get("label") or "").strip()
        basis = "tolkning" if edge.get("interpretation") else "källbelagd"
        line = f"- {source} → {target}: {label} ({basis})"
        line += _source_refs(edge.get("source_refs"))
        edge_lines.append(line)
    parts = []
    if node_lines:
        parts.append("Noder:\n" + "\n".join(node_lines))
    if edge_lines:
        parts.append("Kanter:\n" + "\n".join(edge_lines))
    return "\n\n".join(parts)


def _source_refs(refs: object) -> str:
    if not isinstance(refs, list):
        return ""
    names = [str(ref).strip() for ref in refs if str(ref).strip()]
    return f" [källor: {', '.join(names)}]" if names else ""


def artifact_readable_text(artifact: WorkspaceArtifact) -> str:
    if artifact.kind == "relations":
        return relation_plain_text(artifact.content)
    return artifact_plain_text(artifact.content)


def inventory_row(artifact: WorkspaceArtifact, workspace_id: str) -> dict:
    """Same inventory fields as an uploaded file. The id is the draft id."""
    return {
        "source_object_id": artifact.id,
        "filename": artifact.title,
        "workspace_id": workspace_id,
        "knowledge_status": "ready",
    }


async def ready_created_document(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    document_id: str | None,
) -> WorkspaceArtifact | None:
    if not document_id:
        return None
    artifact = await session.get(WorkspaceArtifact, document_id)
    if (
        artifact is None
        or artifact.workspace_id != workspace.id
        or artifact.kind not in _READABLE_KINDS
        or artifact.status != "ready"
    ):
        return None
    return artifact


async def ready_document_ids(session: AsyncSession, workspace_id: str) -> set[str]:
    rows = await session.scalars(select(WorkspaceArtifact.id).where(
        WorkspaceArtifact.workspace_id == workspace_id,
        WorkspaceArtifact.kind.in_(_READABLE_KINDS),
        WorkspaceArtifact.status == "ready",
    ))
    return set(rows)


def _document_set_token(item: object) -> str | None:
    if isinstance(item, str) and item.strip():
        return item.strip()
    if type(item) is int:
        return str(item)
    if type(item) is float and item == item and item.is_integer():
        return str(int(item))
    if isinstance(item, dict):
        return _document_set_token(item.get("source_id", item.get("sourceId")))
    return None


def document_set_source_tokens(arguments: dict) -> list[str]:
    """Accept string ids, numeric ids, or a comma-separated list from the model."""
    raw = arguments.get("source_ids", arguments.get("sourceIds"))
    tokens: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            token = _document_set_token(item)
            if token:
                tokens.append(token)
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("["):
            try:
                return document_set_source_tokens({"source_ids": json.loads(text)})
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        tokens.extend(part for part in re.split(r"[\s,;]+", text) if part)
    else:
        token = _document_set_token(raw)
        if token:
            tokens.append(token)
        elif isinstance(arguments.get("source_id"), str) and arguments["source_id"].strip():
            tokens.append(arguments["source_id"].strip())
    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped[:40]


def resolve_document_set_source_ids(tokens: list[str], inventory: list[dict]) -> list[str]:
    """Map model tokens onto source_object_id values; filename fragments like '17' are allowed."""
    known = {str(row.get("source_object_id") or "") for row in inventory if row.get("source_object_id")}
    resolved: list[str] = []
    for token in tokens:
        if token in known:
            if token not in resolved:
                resolved.append(token)
            continue
        needle = token.casefold()
        matches = [
            str(row["source_object_id"])
            for row in inventory
            if row.get("source_object_id")
            and (
                str(row.get("filename") or "").casefold() == needle
                or needle in re.split(r"[^0-9a-zåäö]+", str(row.get("filename") or "").casefold())
            )
        ]
        if len(matches) == 1:
            if matches[0] not in resolved:
                resolved.append(matches[0])
        elif not matches and token not in resolved:
            resolved.append(token)
    return resolved[:40]


def present_document_call(
    name: str,
    arguments: dict,
    artifact_ids: set[str],
    *,
    inventory: list[dict] | None = None,
) -> tuple[str, dict]:
    """Opening a created document uses the same source id as any other document."""
    source_id = str(arguments.get("source_id") or "")
    if name == "show_document" and source_id in artifact_ids:
        return "show_artifact", {"artifact_id": source_id}
    if name == "show_document_set" and inventory is not None:
        tokens = document_set_source_tokens(arguments)
        source_ids = resolve_document_set_source_ids(tokens, inventory)
        title = str(arguments.get("title") or "").strip()
        if title and source_ids:
            return name, {**arguments, "title": title, "source_ids": source_ids}
    return name, arguments


def created_document_read(artifact: WorkspaceArtifact, quote: str | None) -> dict:
    text = artifact_readable_text(artifact)
    if quote:
        window = text if quote.casefold() in text.casefold() else ""
        return {
            "status": "completed",
            "source_id": artifact.id,
            "filename": artifact.title,
            "match": "around" if window else "none",
            "text": window[:20000],
            "ingest_status": "ready",
        }
    clipped = text[:20000]
    return {
        "status": "completed",
        "source_id": artifact.id,
        "filename": artifact.title,
        "text": clipped,
        "ingest_status": "ready",
        "truncated": len(text) > len(clipped),
    }


def created_document_rows(
    artifacts: list[WorkspaceArtifact],
    active_id: str | None,
    *,
    open_ids: set[str],
) -> list[dict]:
    """Open document tabs, identified only. Their text stays out of the turn."""
    ready = [
        row for row in artifacts
        if row.kind == "document" and row.status == "ready" and row.id in open_ids
    ]
    ready.sort(key=lambda row: (row.id != active_id, row.title))
    return [
        {
            "artifact_id": artifact.id,
            "title": artifact.title,
            "status": artifact.status,
            "shown": artifact.id == active_id,
        }
        for artifact in ready
    ]


def relation_rows(
    artifacts: list[WorkspaceArtifact],
    active_id: str | None,
    *,
    open_ids: set[str],
) -> list[dict]:
    """Open relation-map tabs, by id. The graph is not copied into the turn."""
    ready = [
        row for row in artifacts
        if row.kind == "relations" and row.status == "ready" and row.id in open_ids
    ]
    ready.sort(key=lambda row: (row.id != active_id, row.title))
    return [
        {
            "artifact_id": artifact.id,
            "title": artifact.title,
            "status": artifact.status,
            "shown": artifact.id == active_id,
        }
        for artifact in ready
    ]


def matching_artifact_id(artifacts: list[WorkspaceArtifact], terms: list[str]) -> str | None:
    """One ready draft the request names, or the only draft when the request names none."""
    if terms:
        hits = [row.id for row in artifacts if all(term in row.title.casefold() for term in terms)]
        return hits[0] if len(hits) == 1 else None
    return artifacts[0].id if len(artifacts) == 1 else None


def _contains_all(row: dict, texts: dict[str, str], terms: list[str]) -> bool:
    haystack = f"{row.get('filename', '')}\n{texts.get(row['source_object_id'], '')}".casefold()
    return all(term in haystack for term in terms)


async def source_for_open_request(
    session: AsyncSession,
    *,
    workspace_id: str | None,
    actor_user_id: str | None,
    message: str,
    history: list[tuple[str, str, str | None]],
) -> str | None:
    earlier = [entry[1] for entry in history if entry[0] == "user"]
    terms = open_request_terms(message, earlier)
    if terms is None or actor_user_id is None or workspace_id is None:
        return None
    actor = await session.get(UserAccount, actor_user_id)
    workspace = await session.get(VoiceWorkspace, workspace_id) if actor is not None else None
    if actor is None or workspace is None or workspace.owner_user_id != actor.id:
        return None
    inventory = await voice_document_inventory(session, workspace, actor)
    ids = [row["source_object_id"] for row in inventory]
    rows = list(await session.scalars(select(StoredObject).where(StoredObject.id.in_(ids)))) if ids else []
    texts = {row.id: row.extracted_text or "" for row in rows}
    assistant_text = "\n".join(entry[1] for entry in history if entry[0] == "assistant")
    return matching_source_id(inventory, texts, terms, assistant_text)


async def artifact_for_open_request(
    session: AsyncSession,
    *,
    workspace_id: str | None,
    actor_user_id: str | None,
    message: str,
    history: list[tuple[str, str, str | None]],
) -> str | None:
    earlier = [entry[1] for entry in history if entry[0] == "user"]
    terms = open_request_terms(message, earlier)
    if terms is None or actor_user_id is None or workspace_id is None:
        return None
    actor = await session.get(UserAccount, actor_user_id)
    workspace = await session.get(VoiceWorkspace, workspace_id) if actor is not None else None
    if actor is None or workspace is None or workspace.owner_user_id != actor.id:
        return None
    rows = list(await session.scalars(select(WorkspaceArtifact).where(
        WorkspaceArtifact.workspace_id == workspace.id,
        WorkspaceArtifact.kind.in_(_READABLE_KINDS),
        WorkspaceArtifact.status == "ready",
    )))
    return matching_artifact_id(rows, terms)


async def voice_document_context(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    user: UserAccount,
    *,
    state: WorkspaceState | None = None,
) -> dict:
    inventory = await voice_document_inventory(session, workspace, user)
    by_id = {row["source_object_id"]: row for row in inventory}
    view = state if state is not None else WorkspaceState.model_validate(workspace.state)
    chosen = select_excerpt_ids(inventory, [tab.source_id for tab in view.documents])
    open_ids = open_artifact_ids(view)
    artifacts = list(await session.scalars(select(WorkspaceArtifact).where(
        WorkspaceArtifact.workspace_id == workspace.id,
        WorkspaceArtifact.kind.in_(_READABLE_KINDS),
        WorkspaceArtifact.status == "ready",
    )))
    created = [
        inventory_row(artifact, workspace.workspace_id)
        for artifact in artifacts
        if artifact.status == "ready"
    ]
    active_set = next(
        (
            document_set for document_set in view.document_sets
            if view.view == "document_set" and document_set.id == view.active_document_set_id
        ),
        None,
    )
    return {
        "available_documents": [*inventory, *created],
        "open_documents": [
            {
                "source_id": source_id,
                "filename": by_id[source_id]["filename"],
                "knowledge_status": by_id[source_id]["knowledge_status"],
            }
            for source_id in chosen
        ],
        "created_documents": created_document_rows(
            artifacts, view.active_artifact_id, open_ids=open_ids,
        ),
        "relation_maps": relation_rows(
            artifacts, view.active_artifact_id, open_ids=open_ids,
        ),
        "shown_document_set": None if active_set is None else {
            "title": active_set.title,
            "documents": [
                {
                    "source_id": source_id,
                    "filename": by_id[source_id]["filename"],
                }
                for source_id in active_set.source_ids
                if source_id in by_id
            ],
        },
    }
