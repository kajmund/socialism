"""Real-service document checks composed by the isolated workspace live runner.

The caller provides the migrated isolated database, authenticated ASGI client,
real runtime configuration, disabled background scheduling, and observation of
actual external calls. No replacement providers or models are installed here.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.database.models import (
    CanonicalDocumentRecord,
    DocumentKnowledgeItem,
    DocumentVersionRecord,
    Job,
    StoredObject,
    TextUnitRecord,
)
from app.services.document_ingest_job import run_document_ingest_job
from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.models import (
    KnowledgeDocument,
    KnowledgeQuery,
    KnowledgeScope,
    KnowledgeScopeRequiredError,
)
from app.services.knowledge.scope import shared_scope
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.research.composition import require_knowledge_vector_store
from app.services.research.knowledge_source import KnowledgeResearchSource
from app.services.research.models import ResearchContext, ResearchNeed


async def run_checks(factory, appclient, report: dict, observation) -> dict:
    checks = report.setdefault("document_ingest_checks", [])
    fixtures = report.setdefault(
        "document_fixtures",
        {"workspaces": [], "chats": [], "sources": [], "jobs": [], "shared_documents": []},
    )
    prefix = f"workspace-live-{uuid4().hex[:10]}"
    common = await _create_chat(appclient, fixtures, title=f"{prefix} företag")
    first = await _create_workspace(appclient, fixtures, f"{prefix} klient A")
    second = await _create_workspace(appclient, fixtures, f"{prefix} klient B")
    chat_a = await _create_chat(appclient, fixtures, title=f"{prefix} avtal A", workspace_id=first)
    chat_b = await _create_chat(appclient, fixtures, title=f"{prefix} avtal B", workspace_id=second)
    cases = [
        ("company", common, "1 februari 2027"),
        ("client_a", chat_a, "3 mars 2028"),
        ("client_b", chat_b, "7 augusti 2029"),
    ]
    sources = {}
    for label, chat, date in cases:
        print(json.dumps({"stage": "real_workspace_document_ingest", "scope": label}), flush=True)
        source = await _upload(appclient, fixtures, chat["id"], _agreement(label, date))
        result = await _run_ingest(factory, source["knowledge_job_id"])
        snapshot = await _snapshot(factory, source["id"])
        sources[label] = {**source, **snapshot, "chat_id": chat["id"], "start_date": date}
        _check(checks, f"{label}_real_ingest_ready", result["status"] == "ready", result)
        report.setdefault("automatic_document_knowledge", {})[label] = {
            "active_generated_items_by_kind": snapshot["generated_items_by_kind"],
            "qa_count": snapshot["qa_count"],
            "items_created": result.get("items_created"),
            "successful_batches": result.get("successful_batches"),
            "failed_batches": result.get("failed_batches"),
        }
        _check(
            checks,
            f"{label}_sql_units_have_canonical_version",
            bool(snapshot["text_unit_ids"])
            and snapshot["unit_version_ids"] == [snapshot["document_version_id"]],
        )
    customer_id = common["customer_id"]
    common_id = common["workspace_id"]
    scope = KnowledgeScope(
        customer_id=customer_id, workspace_id=first, readable_workspace_ids=(common_id, first)
    )
    store = require_knowledge_vector_store()
    embeddings = OpenAIEmbeddingProvider.from_settings()
    allowed = {sources["company"]["id"], sources["client_a"]["id"]}
    await _scope_checks(factory, appclient, checks, chat_a=chat_a, sources=sources, scope=scope)
    await run_manual_qa_checks(
        factory,
        appclient,
        report,
        {
            "company_chat": common,
            "client_a_chat": chat_a,
            "sources": sources,
        },
    )
    before = await _snapshot(factory, sources["client_a"]["id"])
    repeated = await _run_ingest(factory, sources["client_a"]["knowledge_job_id"])
    after = await _snapshot(factory, sources["client_a"]["id"])
    _check(
        checks,
        "same_hash_reuses_canonical_ids_and_qa_revisions",
        repeated["reused_version"] and before == after,
    )
    shared_id = await _shared_source(factory, prefix, store, embeddings)
    fixtures["shared_documents"].append(shared_id)
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        context = ResearchContext(scope)
        need = ResearchNeed(
            "global-check", "Vad betyder skriftlig uppsägning av avtal?", "Verifiera global kunskap"
        )
        global_results = await KnowledgeResearchSource(
            provider, source_type="domain_knowledge"
        ).research(need, context)
        private_results = await KnowledgeResearchSource(
            provider, source_type="case_knowledge"
        ).research(need, context)
    global_found = [item for item in global_results if item.status == "found"]
    private_found = [item for item in private_results if item.status == "found"]
    _check(
        checks,
        "global_knowledge_remains_shared",
        bool(global_found)
        and all(
            item.metadata.get("scope_type") == "shared" and item.metadata.get("customer_id") is None
            for item in global_found
        ),
        {"source_ids": [item.source_id for item in global_found]},
    )
    _check(
        checks,
        "customer_documents_never_become_global_knowledge",
        all(item.source_id not in allowed for item in global_found),
    )
    _check(
        checks,
        "private_source_never_relabels_global_knowledge",
        all(item.metadata.get("scope_type") == "customer" for item in private_found),
    )
    return {
        "company_chat": common,
        "client_a_chat": chat_a,
        "client_b_chat": chat_b,
        "sources": sources,
        "shared_document_id": shared_id,
    }


async def _scope_checks(factory, appclient, checks, *, chat_a, sources, scope):
    store = require_knowledge_vector_store()
    embeddings = OpenAIEmbeddingProvider.from_settings()
    allowed = {sources["company"]["id"], sources["client_a"]["id"]}
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        hits = await provider.search(
            KnowledgeQuery(
                "När börjar avtalet gälla?",
                scope,
                limit=12,
                filters={"knowledge_kind": "document_item"},
            )
        )
        default_hits = await provider.search(
            KnowledgeQuery(
                "När börjar avtalet gälla?", KnowledgeScope(customer_id=scope.customer_id), limit=12
            )
        )
    _check(
        checks,
        "client_discovery_excludes_other_client",
        {hit.document_id for hit in hits}.issubset(allowed),
        {"source_ids": sorted({hit.document_id for hit in hits})},
    )
    _check(
        checks,
        "default_workspace_is_company_only",
        bool(default_hits)
        and {hit.document_id for hit in default_hits} == {sources["company"]["id"]},
    )
    await _check_originals(factory, appclient, checks, chat_a["id"], hits=hits)
    denied = await appclient.get(
        f"/workspace-chats/{chat_a['id']}/files/{sources['client_b']['id']}"
    )
    _check(checks, "other_client_original_file_hidden", denied.status_code == 404)
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        selected = KnowledgeScope(
            customer_id=scope.customer_id,
            workspace_id=scope.workspace_id,
            readable_workspace_ids=scope.readable_workspace_ids,
            allowed_source_object_ids=(sources["client_b"]["id"],),
        )
        try:
            await provider.search(KnowledgeQuery("avtal", selected))
        except KnowledgeScopeRequiredError:
            rejected = True
        else:
            rejected = False
    _check(checks, "foreign_workspace_manifest_rejected_by_sql", rejected)


async def _create_workspace(client, fixtures: dict, name: str) -> str:
    response = await client.post("/workspaces", json={"name": name})
    if response.status_code != 201:
        raise RuntimeError(f"Workspace creation returned {response.status_code}")
    workspace_id = response.json()["id"]
    fixtures["workspaces"].append(workspace_id)
    return workspace_id


async def _create_chat(
    client, fixtures: dict, *, title: str, workspace_id: str | None = None
) -> dict:
    body = {"title": title}
    if workspace_id is not None:
        body["workspace_id"] = workspace_id
    response = await client.post("/workspace-chats", json=body)
    if response.status_code != 201:
        raise RuntimeError(f"Workspace chat creation returned {response.status_code}")
    chat = response.json()
    fixtures["chats"].append(chat["id"])
    return chat


async def _upload(client, fixtures: dict, chat_id: str, body: str) -> dict:
    response = await client.post(
        f"/workspace-chats/{chat_id}/files",
        files={"file": ("avtal.md", body.encode(), "text/markdown")},
    )
    if response.status_code != 201:
        raise RuntimeError(f"Workspace upload returned {response.status_code}")
    source = response.json()
    fixtures["sources"].append(source["id"])
    fixtures["jobs"].append(source["knowledge_job_id"])
    return source


async def _run_ingest(factory, job_id: str) -> dict:
    async with factory.begin() as session:
        job = await session.get(Job, job_id)
        job.status = "running"
    result = await run_document_ingest_job(factory, job_id=job_id)
    async with factory.begin() as session:
        job = await session.get(Job, job_id)
        job.status, job.result = "succeeded", result
    return result


async def _snapshot(factory, source_id: str) -> dict:
    async with factory() as session:
        document = await session.scalar(
            select(CanonicalDocumentRecord).where(
                CanonicalDocumentRecord.source_object_id == source_id
            )
        )
        version = await session.scalar(
            select(DocumentVersionRecord).where(
                DocumentVersionRecord.document_id == document.id,
                DocumentVersionRecord.superseded_at.is_(None),
            )
        )
        units = list(
            await session.scalars(
                select(TextUnitRecord).where(TextUnitRecord.document_version_id == version.id)
            )
        )
        items = list(
            await session.scalars(
                select(DocumentKnowledgeItem).where(
                    DocumentKnowledgeItem.source_object_id == source_id,
                    DocumentKnowledgeItem.status == "active",
                )
            )
        )
        qa = [item for item in items if item.kind == "qa"]
        generated_counts = {}
        for item in items:
            if item.origin == "generated":
                generated_counts[item.kind] = generated_counts.get(item.kind, 0) + 1
        return {
            "document_id": document.id,
            "document_version_id": version.id,
            "text_unit_ids": sorted(unit.id for unit in units),
            "unit_version_ids": sorted({unit.document_version_id for unit in units}),
            "qa_count": len(qa),
            "qa_revisions": sorted((item.id, item.revision) for item in qa),
            "generated_items_by_kind": generated_counts,
        }


async def run_manual_qa_checks(factory, appclient, report: dict, ingest: dict) -> dict:
    """Exercise actual editable Q&A independently of optional auto-generation."""
    source = ingest["sources"]["client_a"]
    chat = ingest["client_a_chat"]
    async with factory() as session:
        units = list(
            await session.scalars(
                select(TextUnitRecord)
                .where(
                    TextUnitRecord.document_id == source["document_id"],
                    TextUnitRecord.document_version_id == source["document_version_id"],
                )
                .order_by(TextUnitRecord.ordinal)
            )
        )
        unit = next((unit for unit in units if source["start_date"] in unit.text), None)
        if unit is None:
            raise RuntimeError("Ingested client document has no original TextUnit")
        original = {
            "id": unit.id,
            "locator": unit.locator,
            "text": unit.text,
            "document_version_id": unit.document_version_id,
        }
    question = "När börjar avtalet gälla?"
    response = await appclient.post(
        f"/underlag/{source['id']}/knowledge",
        params={"workspace_id": chat["workspace_id"]},
        json={
            "kind": "qa",
            "title": "Avtalets startdatum",
            "question": question,
            "content": f"Avtalet börjar gälla den {source['start_date']}.",
            "anchors": [
                {
                    "anchor_type": "text",
                    "locator": original["locator"],
                    "exact_text": original["text"],
                }
            ],
            "supporting_text_unit_ids": [original["id"]],
        },
    )
    if response.status_code != 201:
        raise RuntimeError(f"Manual Q&A returned {response.status_code}: {response.text[:400]}")
    item = response.json()
    scope = KnowledgeScope(
        customer_id=chat["customer_id"],
        workspace_id=chat["workspace_id"],
        readable_workspace_ids=(ingest["company_chat"]["workspace_id"], chat["workspace_id"]),
        allowed_source_object_ids=(source["id"],),
        allowed_document_version_ids=(original["document_version_id"],),
    )
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(
            session, require_knowledge_vector_store(), OpenAIEmbeddingProvider.from_settings()
        )
        hits = await provider.search(
            KnowledgeQuery(
                question,
                scope,
                limit=12,
                filters={
                    "knowledge_kind": "document_item",
                    "item_kind": "qa",
                    "document_knowledge_item_id": item["id"],
                },
            )
        )
    actual = [hit for hit in hits if hit.metadata.get("document_knowledge_item_id") == item["id"]]
    checks = report.setdefault("document_ingest_checks", [])
    _check(
        checks,
        "manual_qa_real_embedding_and_grounding",
        bool(actual)
        and all(
            hit.metadata.get("qa_snapshot", {}).get("question") == question
            and hit.metadata.get("item_revision") == item["revision"]
            and hit.metadata.get("document_version_id") == original["document_version_id"]
            and hit.excerpt == original["text"]
            for hit in actual
        ),
        {"item_id": item["id"], "revision": item["revision"], "text_unit_id": original["id"]},
    )
    await _check_originals(factory, appclient, checks, chat["id"], hits=actual)
    report["manual_qa_observation"] = {
        "item_id": item["id"],
        "revision": item["revision"],
        "source_object_id": source["id"],
        "document_version_id": original["document_version_id"],
        "text_unit_id": original["id"],
        "grounded_hit_count": len(actual),
    }
    return item


async def _check_originals(factory, client, checks: list, chat_id: str, *, hits) -> None:
    valid, api_valid = True, True
    for hit in hits:
        async with factory() as session:
            unit = await session.get(TextUnitRecord, hit.metadata["text_unit_id"])
            source = await session.get(StoredObject, hit.metadata["source_object_id"])
            valid = (
                valid
                and unit is not None
                and hit.excerpt == unit.text
                and hit.metadata["document_version_id"] == unit.document_version_id
                and source.workspace_id == hit.metadata["workspace_id"]
            )
        response = await client.get(
            f"/workspace-chats/{chat_id}/sources/{hit.metadata['source_object_id']}",
            params={
                "text_unit_id": hit.metadata["text_unit_id"],
                "document_version_id": hit.metadata["document_version_id"],
            },
        )
        api_valid = (
            api_valid
            and response.status_code == 200
            and response.json().get("excerpt") == hit.excerpt
        )
    _check(checks, "discovery_evidence_is_sql_original_passage", valid)
    _check(checks, "source_citation_opens_original_passage", api_valid)


async def _shared_source(factory, prefix: str, store, embeddings) -> str:
    source_id = f"global-{uuid4().hex}"
    text = (
        "Skriftlig uppsägning av avtal innebär att meddelandet om uppsägning dokumenteras i skrift."
    )
    async with factory() as session:
        await ingest_extracted_source(
            session,
            extracted=ExtractedDocument([ExtractedBlock(text, "line:1")]),
            document=KnowledgeDocument(
                document_id=source_id,
                provider="supabase",
                external_id=f"shared-fixture:{prefix}",
                title="Allmän avtalskunskap",
                mime_type="text/plain",
                scope=KnowledgeScope(customer_id=None, scope_type="shared"),
            ),
            source_type="shared_reference",
            canonical_uri=f"shared-fixture:{prefix}",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            scope=shared_scope(),
            embeddings=embeddings,
            vector_store=store,
        )
    return source_id


def _agreement(label: str, date: str) -> str:
    return f"""# Avtal – syntetiskt integrationsunderlag {label}

Avtalet börjar gälla den {date}. Månadsavgiften är 2750 kronor. Avtalets uppsägningstid är sex månader.

## Frågor och svar

Fråga: När börjar avtalet gälla?
Svar: Avtalet börjar gälla den {date}.

Fråga: Hur lång är avtalets uppsägningstid?
Svar: Avtalets uppsägningstid är sex månader.
"""


def _check(checks: list, name: str, passed: bool, details: dict | None = None) -> None:
    checks.append(
        {"name": name, "passed": bool(passed), **({"details": details} if details else {})}
    )
