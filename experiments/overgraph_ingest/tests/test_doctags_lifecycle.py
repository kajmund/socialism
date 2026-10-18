from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.doctags.catalog import EMPLOYMENT_TYPE, PERMANENT, PROBATIONARY
from overgraph_ingest.doctags.lifecycle import (
    apply_automatic_tags,
    correct_tag_value,
    delete_document,
    is_source_verified,
    prove_lifecycle,
    restore_document,
    visible_tags,
)
from overgraph_ingest.doctags.close import (
    review_document_tags_close,
    write_document_tags_close_baseline,
    write_document_tags_close_table,
)
from overgraph_ingest.doctags.lifecycle_eval import (
    review_document_tags_lifecycle,
    run_document_tags_lifecycle,
    write_document_tags_lifecycle_baseline,
    write_document_tags_lifecycle_table,
)
from overgraph_ingest.doctags.schema import (
    KIND_EXTRACTED,
    KIND_USER_LABEL,
    REJECTED,
    USER_CORRECTED,
    WITHDRAWN,
)
from overgraph_ingest.doctags.store import (
    add_user_tag,
    filter_documents,
    iter_tags,
    persist_proposals,
    store_classification,
    store_tag,
)
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.ingest import build_parser
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_document_tags_close_baseline,
    load_document_tags_lifecycle_baseline,
    load_document_tags_run_baseline,
)

ROOT = Path(__file__).resolve().parents[1]


def _writer(tmp_path: Path) -> tuple[object, GraphWriter]:
    db = open_database(tmp_path / "life", 8)
    return db, GraphWriter(db, batch_size=50)


def _classify(writer: GraphWriter, document_id: str = "doc-1") -> None:
    store_classification(
        writer,
        document_id=document_id,
        predicted_type="employment_agreement",
        confidence=0.9,
        probabilities={"employment_agreement": 0.9},
        model="jev-1.13.0",
        taxonomy_version="document-types-v1",
        tenant_id="t1",
        workspace_id="w1",
        extra_props={"relative_path": "a.docx", "document_id": document_id},
    )


def _proposal(value: str, validated: bool = True, tag_class: str = EMPLOYMENT_TYPE) -> dict[str, object]:
    return {
        "document_id": "doc-1",
        "relative_path": "a.docx",
        "tag_class": tag_class,
        "value": value,
        "origin": "structure",
        "source": {
            "unit_id": "u1" if validated else "",
            "excerpt": "text" if validated else "",
            "start": 0 if validated else None,
            "end": 4 if validated else None,
            "validated": validated,
        },
    }


def test_user_label_is_not_an_extracted_property(tmp_path: Path) -> None:
    db, writer = _writer(tmp_path)
    try:
        _classify(writer)
        user = add_user_tag(
            writer,
            document_id="doc-1",
            relative_path="a.docx",
            tag_class="user_label",
            value="important_customer",
            tenant_id="t1",
            workspace_id="w1",
            display_value="Viktig kund",
        )
        extracted = store_tag(
            writer,
            document_id="doc-1",
            relative_path="a.docx",
            tag_class=EMPLOYMENT_TYPE,
            value=PERMANENT,
            origin="structure",
            tenant_id="t1",
            workspace_id="w1",
            source={"unit_id": "u1", "excerpt": "tillsvidare", "start": 0, "end": 11, "validated": True},
        )
        bare = store_tag(
            writer,
            document_id="doc-1",
            relative_path="a.docx",
            tag_class="notice_period",
            value="1_month",
            origin="jev",
            tenant_id="t1",
            workspace_id="w1",
        )
        assert user["kind"] == KIND_USER_LABEL
        assert extracted["kind"] == KIND_EXTRACTED
        assert is_source_verified(user) is False
        assert is_source_verified(extracted) is True
        assert is_source_verified(bare) is False
    finally:
        db.close()


def test_value_correction_blocks_old_automatic_value(tmp_path: Path) -> None:
    db, writer = _writer(tmp_path)
    try:
        _classify(writer)
        first = store_tag(
            writer,
            document_id="doc-1",
            relative_path="a.docx",
            tag_class=EMPLOYMENT_TYPE,
            value=PROBATIONARY,
            origin="structure",
            tenant_id="t1",
            workspace_id="w1",
        )
        corrected = correct_tag_value(
            writer,
            tag_id=first["tag_id"],
            value=PERMANENT,
            display_value="Tillsvidare",
        )
        assert corrected["rejected"]["review_status"] == REJECTED
        assert corrected["created"]["review_status"] == USER_CORRECTED
        assert persist_proposals(writer, [_proposal(PROBATIONARY)], tenant_id="t1", workspace_id="w1") == 0
        visible = visible_tags(writer, document_id="doc-1", tenant_id="t1", workspace_id="w1")
        assert {(row["tag_class"], row["value"]) for row in visible} == {(EMPLOYMENT_TYPE, PERMANENT)}
    finally:
        db.close()


def test_reingest_withdraws_stale_unreviewed_tags(tmp_path: Path) -> None:
    db, writer = _writer(tmp_path)
    try:
        _classify(writer)
        apply_automatic_tags(
            writer,
            [_proposal(PERMANENT), _proposal("1_month", tag_class="notice_period")],
            document_id="doc-1",
            tenant_id="t1",
            workspace_id="w1",
        )
        apply_automatic_tags(
            writer,
            [_proposal(PERMANENT)],
            document_id="doc-1",
            tenant_id="t1",
            workspace_id="w1",
        )
        notice = next(row for row in iter_tags(writer) if row["tag_class"] == "notice_period")
        assert notice["review_status"] == WITHDRAWN
        assert filter_documents(
            writer,
            tenant_id="t1",
            workspace_id="w1",
            tag_class="notice_period",
            tag_value="1_month",
        ) == []
        assert "a.docx" in filter_documents(
            writer,
            tenant_id="t1",
            workspace_id="w1",
            tag_class=EMPLOYMENT_TYPE,
            tag_value=PERMANENT,
        )
    finally:
        db.close()


def test_delete_hides_document_and_keeps_user_decisions(tmp_path: Path) -> None:
    db, writer = _writer(tmp_path)
    try:
        _classify(writer)
        add_user_tag(
            writer,
            document_id="doc-1",
            relative_path="a.docx",
            tag_class="user_label",
            value="needs_review",
            tenant_id="t1",
            workspace_id="w1",
            display_value="Behöver granskas",
        )
        delete_document(writer, "doc-1")
        assert filter_documents(writer, tenant_id="t1", workspace_id="w1") == []
        restore_document(writer, "doc-1")
        store_classification(
            writer,
            document_id="doc-1",
            predicted_type="consulting_agreement",
            confidence=0.2,
            probabilities={"consulting_agreement": 0.2},
            model="jev-1.13.0",
            taxonomy_version="document-types-v1",
            tenant_id="t1",
            workspace_id="w1",
        )
        assert "a.docx" in filter_documents(
            writer,
            tenant_id="t1",
            workspace_id="w1",
            tag_class="user_label",
            tag_value="needs_review",
        )
        document = writer.get_document("doc-1")
        assert document.props["predicted_type"] == "consulting_agreement"
        assert document.props["effective_type"] == "consulting_agreement"
    finally:
        db.close()


def test_lifecycle_proof_and_freeze(tmp_path: Path) -> None:
    db, writer = _writer(tmp_path)
    try:
        proof = prove_lifecycle(writer)
        assert proof["user_label_kind"] == KIND_USER_LABEL
        assert proof["user_label_source_verified"] is False
        assert proof["probationary_stays_rejected"] is True
        assert proof["notice_withdrawn"] is True
        assert proof["deleted_hidden_from_filter"] is True
        assert proof["user_label_survives_delete"] is True
        assert proof["restored_effective_type_locked"] is True
    finally:
        db.close()
    payload = review_document_tags_lifecycle()
    payload["proof"] = proof
    path = write_document_tags_lifecycle_baseline(payload, tmp_path / "life.json")
    write_document_tags_lifecycle_table(payload, tmp_path)
    with pytest.raises(FileExistsError):
        write_document_tags_lifecycle_baseline(payload, path)


def test_cli_and_conclusions() -> None:
    parser = build_parser()
    args = parser.parse_args(["--db", "data/extra-overgraph-phase2", "--document-tags-lifecycle"])
    assert args.document_tags_lifecycle is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_best_variant"] == "A"
    assert RETRIEVAL_CONCLUSIONS["document_tags_b_is_experimental_semantic_alternative"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_automatic_tags_are_proposals"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_user_label_distinct_from_extracted_property"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_lifecycle"] == "reviewed_v1"
    args = parser.parse_args(["--db", "data/extra-overgraph-phase2", "--document-tags-close"])
    assert args.document_tags_close is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_experiment"] == "closed_v1"
    assert RETRIEVAL_CONCLUSIONS["document_tags_do_not_run_more_jev_on_16_docs"] is True
    assert RETRIEVAL_CONCLUSIONS["document_catalog_reuses_canonical_document"] is True
    assert RETRIEVAL_CONCLUSIONS["document_catalog_do_not_import_overgraph_ingest"] is True


def test_frozen_lifecycle_baseline() -> None:
    payload = load_document_tags_lifecycle_baseline()
    assert payload["does_not_run_jev"] is True
    assert payload["a_is_cheap_ingest_candidate"] is True
    assert payload["b_is_experimental_semantic_alternative"] is True
    assert payload["automatic_tags_are_proposals"] is True
    assert payload["headline"]["proof_ok"] is True
    assert payload["proof"]["probationary_stays_rejected"] is True
    assert payload["proof"]["user_label_survives_delete"] is True
    run = load_document_tags_run_baseline()
    assert run["variants"]["A"]["hits"] == 32
    assert run["variants"]["B"]["hits"] == 32
    with pytest.raises(FileExistsError):
        write_document_tags_lifecycle_baseline(
            review_document_tags_lifecycle(),
            ROOT / "baselines" / "phase2-document-tags-lifecycle-v1.json",
        )
    closed = load_document_tags_close_baseline()
    assert closed["experiment_closed"] is True
    assert closed["do_not_run_more_jev_on_16_docs"] is True
    assert closed["identity"]["user_decisions_belong_to_canonical_document"] is True
    assert closed["deletion"]["experiment_delete_is_archive_only"] is True
    with pytest.raises(FileExistsError):
        write_document_tags_close_baseline(
            review_document_tags_close(),
            ROOT / "baselines" / "phase2-document-tags-close-v1.json",
        )


def test_close_freeze_refuses_overwrite(tmp_path: Path) -> None:
    payload = review_document_tags_close()
    assert payload["does_not_run_jev"] is True
    assert payload["experiment_closed"] is True
    assert payload["do_not_run_more_jev_on_16_docs"] is True
    assert payload["carry_to_socialism"]["reuse_canonical_document"] is True
    assert payload["deletion"]["purge_not_solved_in_experiment"] is True
    path = write_document_tags_close_baseline(payload, tmp_path / "close.json")
    write_document_tags_close_table(payload, tmp_path)
    with pytest.raises(FileExistsError):
        write_document_tags_close_baseline(payload, path)


def test_run_lifecycle_does_not_call_jev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "overgraph_ingest.doctags.lifecycle_eval.ROOT",
        tmp_path,
    )
    payload = run_document_tags_lifecycle(db_path=tmp_path / "proof")
    assert payload["does_not_run_jev"] is True
    assert payload["models_not_run"] is True
    assert payload["headline"]["proof_ok"] is True
