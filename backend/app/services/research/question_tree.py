"""Durable recursive question tree above ResearchNeed/provider execution."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.knowledge_scope import customer_scope_key
from app.database.models import (
    EvidenceSetItem,
    EvidenceSetItemNeed,
    ExecutionAttempt,
    ExecutionRun,
    ResearchAnswerChildLink,
    ResearchAnswerEvidenceLink,
    ResearchQuestionAnswer,
    ResearchQuestionNode,
    ResearchRuntimeNeed,
)
from app.jev.service import jev_evaluation_binding
from app.observability.events import EVENT_DATASET_RESEARCH, log_event
from app.observability.research import (
    current_research_stats,
    record_decomposition_exhausted,
    record_question_outcome_counts,
    record_question_step,
    record_research_fallback,
)
from app.services.research.knowledge_question import normalize_research_question
from app.services.research.models import ResearchNeed, ResearchPlan, ResearchSourceType
from app.services.research.progress import (
    PROGRESS_IDEMPOTENCY_KEY_MAX,
    ProgressTracker,
    ResearchProgressEventType,
    append_research_progress_event,
)

QuestionOrigin = Literal["root", "decomposition", "gap"]
AnswerStatus = Literal["answered", "answered_with_gaps", "insufficient_evidence"]
CompletenessStatus = Literal["answered", "answered_with_gaps", "insufficient"]
TRANSIENT_QUESTION_PHASES = frozenset(
    {
        "assessing_atomicity",
        "decomposing",
        "researching",
        "synthesizing",
        "assessing_completeness",
    }
)
_RETIRABLE_PHASES = frozenset({"created", "ready", "decomposed"})
_TERMINAL_QUESTION_PHASES = frozenset(
    {"completed", "unresolved", "not_required", "failed", "evidence_incomplete"}
)
_REJECTION_COUNT_KEYS = (
    "redundant_with_parent",
    "redundant_with_sibling",
    "redundant_with_ancestor",
    "paraphrase",
    "no_semantic_progress",
)
_REDUNDANCY_REASONS = frozenset(
    {
        "redundant_with_parent",
        "redundant_with_sibling",
        "redundant_with_ancestor",
    }
)
_CHILD_EVENT_KEY_PREFIX = len("child:") + 32 + 1
logger = logging.getLogger("app.research.question_tree")


class QuestionTreeError(RuntimeError):
    pass


Researchability = Literal["researchable", "not_researchable", "uncertain"]
Decomposability = Literal["decomposable", "not_decomposable", "uncertain"]
StructureAction = Literal["retrieve", "decompose", "unresolved"]


@dataclass(frozen=True)
class StructureDecision:
    researchability: Researchability
    decomposability: Decomposability
    researchability_reason: str
    decomposability_reason: str
    noul: dict[str, float]
    researchability_confidence: float = 0.0
    decomposability_confidence: float = 0.0
    model_provider: str = "jev"
    model: str = ""
    duration_ms: float = 0.0
    threshold: float = 0.0


@dataclass(frozen=True)
class DecompositionDecision:
    accepted: bool
    noul: dict[str, float]
    rejection_reason: str = ""
    model_provider: str = "jev"
    model: str = ""
    duration_ms: float = 0.0
    threshold: float = 0.0


@dataclass(frozen=True)
class ChildRedundancyDecision:
    """Whether one candidate is a new knowledge need, or a reformulation."""

    accepted: bool
    noul: dict[str, float]
    rejection_reason: str = ""
    model_provider: str = "jev"
    model: str = ""
    duration_ms: float = 0.0
    threshold: float = 0.0


@dataclass(frozen=True)
class ReadinessDecision:
    sufficient: bool
    material_gap: bool
    additional_research_likely_to_change_answer: bool
    noul: dict[str, float]
    model_provider: str = "jev"
    model: str = ""
    duration_ms: float = 0.0


@dataclass(frozen=True)
class CompletenessDecision:
    status: CompletenessStatus
    material_gap: bool
    additional_research_likely_to_change_answer: bool
    noul: dict[str, float]
    model_provider: str = "jev"
    model: str = ""
    duration_ms: float = 0.0


class QuestionTreeController(Protocol):
    async def assess_structure(self, *, question: str) -> StructureDecision: ...

    async def assess_synthesis_readiness(
        self,
        *,
        question: str,
        child_answers: Sequence[AnswerInput],
    ) -> ReadinessDecision: ...

    async def assess_completeness(
        self,
        *,
        question: str,
        answer: str,
        child_answers: Sequence[AnswerInput],
    ) -> CompletenessDecision: ...

    async def validate_decomposition(
        self, *, question: str, children: Sequence[str]
    ) -> DecompositionDecision: ...

    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision: ...


@dataclass(frozen=True)
class GeneratedQuestion:
    question: str
    why_needed: str = ""


@dataclass(frozen=True)
class AnswerInput:
    answer_id: str
    question: str
    answer: str
    status: str


@dataclass(frozen=True)
class GeneratedAnswer:
    text: str
    status: AnswerStatus
    model_provider: str = ""
    model: str = ""
    duration_ms: float = 0.0


class QuestionTreeGenerator(Protocol):
    async def decompose(self, *, question: str) -> Sequence[GeneratedQuestion]: ...

    async def formulate_gap_questions(
        self,
        *,
        question: str,
        answer: str,
        child_answers: Sequence[AnswerInput],
        gap_noul: dict[str, float],
    ) -> Sequence[GeneratedQuestion]: ...

    async def synthesize_leaf(
        self,
        *,
        question: str,
        evidence: Sequence[EvidenceSetItem],
    ) -> GeneratedAnswer: ...

    async def synthesize_parent(
        self,
        *,
        question: str,
        child_answers: Sequence[AnswerInput],
    ) -> GeneratedAnswer: ...


@dataclass(frozen=True)
class QuestionTreeLimits:
    max_depth: int
    max_children: int
    max_questions: int


def _id() -> str:
    return uuid4().hex


def structure_action(researchability: str, decomposability: str) -> StructureAction:
    """Researchability and decomposability choose different actions.

    A clear decomposable question is split even when it can also be retrieved.
    Uncertainty about decomposability does not split a researchable question.
    """
    if decomposability == "decomposable":
        return "decompose"
    if researchability == "researchable":
        return "retrieve"
    return "unresolved"


def _is_best_effort(node: ResearchQuestionNode) -> bool:
    return node.execution_override == "best_effort_retrieval"


def _is_retrieval_leaf(node: ResearchQuestionNode) -> bool:
    if node.research_need_id:
        return True
    return node.phase == "ready" and (
        node.researchability == "researchable" or _is_best_effort(node)
    )


def _is_unresolved_required(node: ResearchQuestionNode) -> bool:
    """A required knowledge need that still has no grounded answer."""
    if node.phase in {"not_required", "failed"}:
        return False
    if node.phase in {"unresolved", "evidence_incomplete"}:
        return True
    return node.completeness == "insufficient"


def _record_knowledge_need_counts(nodes: Sequence[ResearchQuestionNode]) -> None:
    counts = knowledge_need_counts(nodes)
    record_question_outcome_counts(
        unresolved_required=counts["unresolved_required_question_count"],
        not_required=counts["not_required_question_count"],
    )


def knowledge_need_counts(nodes: Sequence[ResearchQuestionNode]) -> dict[str, int]:
    return {
        "unresolved_required_question_count": sum(
            1 for node in nodes if _is_unresolved_required(node)
        ),
        "not_required_question_count": sum(1 for node in nodes if node.phase == "not_required"),
    }


_RESEARCHABILITY_SIGNALS = (
    "bounded_for_evidence_retrieval",
    "can_produce_grounded_answer",
)
_DECOMPOSABILITY_SIGNALS = (
    "robust_answer_requires_multiple_distinct_subconclusions",
    "subconclusions_can_be_researched_separately",
    "subconclusions_would_be_useful_as_reusable_knowledge",
)


def _signal_subset(noul: dict[str, float], keys: tuple[str, ...]) -> dict[str, float]:
    picked = {key: float(noul[key]) for key in keys if key in noul}
    return picked or dict(noul)


def _validation_scores(decision: DecompositionDecision | None) -> dict[str, float]:
    if decision is None:
        return {}
    return {
        key: float(decision.noul[key])
        for key in (
            "independent",
            "narrower",
            "semantic_progress",
            "paraphrase_risk",
            "jointly_sufficient_or_useful",
        )
        if key in decision.noul
    }


async def fail_transient_question_nodes(session: AsyncSession, *, attempt_id: str) -> None:
    """A terminal Attempt must not keep a node in an in-flight phase."""
    for node in await list_question_nodes(session, attempt_id):
        if node.phase not in TRANSIENT_QUESTION_PHASES:
            continue
        node.phase = "failed"
        await emit_question_event(
            session,
            node,
            "question_failed",
            suffix="execution-failed",
            reason="execution_failed",
        )


async def reopen_failed_question_nodes(session: AsyncSession, *, attempt_id: str) -> None:
    """Put crash-failed nodes back in progress. ``failed`` is only set by fail-close."""
    for node in await list_question_nodes(session, attempt_id):
        if node.phase != "failed":
            continue
        node.phase = "researching" if node.research_need_id else "created"
    await session.flush()


async def list_question_nodes(session: AsyncSession, attempt_id: str) -> list[ResearchQuestionNode]:
    result = await session.execute(
        select(ResearchQuestionNode)
        .where(ResearchQuestionNode.attempt_id == attempt_id)
        .order_by(
            ResearchQuestionNode.depth,
            ResearchQuestionNode.created_at,
            ResearchQuestionNode.id,
        )
    )
    return list(result.scalars())


async def get_or_create_root(
    session: AsyncSession,
    *,
    attempt_id: str,
    question: str,
) -> ResearchQuestionNode:
    existing = (
        await session.execute(
            select(ResearchQuestionNode).where(
                ResearchQuestionNode.attempt_id == attempt_id,
                ResearchQuestionNode.parent_question_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    root = ResearchQuestionNode(
        id=_id(),
        attempt_id=attempt_id,
        parent_question_id=None,
        question=question.strip(),
        depth=0,
        created_from="root",
        phase="created",
        atomicity="pending",
    )
    session.add(root)
    await session.flush()
    await emit_question_event(session, root, "question_created", suffix="root")
    return root


def tree_event_idempotency_key(node_id: str, event_type: str, suffix: str) -> str:
    """Key that still fits after the parent Attempt prefixes ``child:{id}:``."""
    key = f"tree:{node_id}:{event_type}:{suffix}"
    if len(key) + _CHILD_EVENT_KEY_PREFIX <= PROGRESS_IDEMPOTENCY_KEY_MAX:
        return key
    digest = hashlib.sha256(suffix.encode()).hexdigest()[:16]
    return f"tree:{node_id}:{event_type}:{digest}"


async def emit_question_event(
    session: AsyncSession,
    node: ResearchQuestionNode,
    event_type: ResearchProgressEventType,
    *,
    suffix: str,
    **payload: object,
) -> None:
    await append_research_progress_event(
        session,
        attempt_id=node.attempt_id,
        event_type=event_type,
        idempotency_key=tree_event_idempotency_key(node.id, event_type, suffix),
        payload={
            "question_id": node.id,
            "parent_question_id": node.parent_question_id,
            "depth": node.depth,
            **payload,
        },
    )
    duration = payload.get("duration_ms")
    log_event(
        logger,
        f"research.{event_type.replace('_', '.')}",
        dataset=EVENT_DATASET_RESEARCH,
        outcome="failure" if event_type == "question_failed" else "success",
        duration_ms=float(duration) if isinstance(duration, (int, float)) else None,
        fields={
            "research": {
                "question_id": node.id,
                "parent_question_id": node.parent_question_id,
                "question_depth": node.depth,
                "need_id": node.research_need_id,
                **payload,
            }
        },
    )


def _question_payload(decision: object, *, step: str) -> dict[str, object]:
    duration_ms = float(getattr(decision, "duration_ms", 0.0))
    model_provider = str(getattr(decision, "model_provider", ""))
    model = str(getattr(decision, "model", ""))
    record_question_step(
        step,
        duration_ms=duration_ms,
        model_provider=model_provider,
        model=model,
    )
    return {
        "duration_ms": duration_ms,
        "model_provider": model_provider,
        "model": model,
    }


def _child_slot_budget(
    parent: ResearchQuestionNode,
    existing_nodes: Sequence[ResearchQuestionNode],
    limits: QuestionTreeLimits,
) -> int:
    if parent.depth >= limits.max_depth:
        return 0
    remaining = max(0, limits.max_questions - len(existing_nodes))
    return min(limits.max_children, remaining)


def _validated_questions(
    *,
    parent: ResearchQuestionNode,
    proposed: Sequence[GeneratedQuestion],
    existing_nodes: Sequence[ResearchQuestionNode],
    limits: QuestionTreeLimits,
    apply_child_budget: bool = True,
) -> tuple[list[GeneratedQuestion], list[dict[str, str]]]:
    """Split proposals into candidates to score and explicit pre-filters.

    ``generated = accepted + rejected + pre_filtered`` counts every proposal.
    Pre-filter reasons are ``empty``, ``duplicate``, and ``child_budget``.
    Decomposition scores candidates before applying the child budget, so a
    rejected candidate does not consume a slot.
    """
    pre_filtered: list[dict[str, str]] = []
    if parent.depth >= limits.max_depth:
        return [], [{"question": draft.question, "reason": "child_budget"} for draft in proposed]
    ancestor_ids: set[str] = set()
    by_id = {row.id: row for row in existing_nodes}
    cursor: ResearchQuestionNode | None = parent
    while cursor is not None:
        ancestor_ids.add(normalize_research_question(cursor.question))
        cursor = by_id.get(cursor.parent_question_id or "")
    known = {normalize_research_question(row.question) for row in existing_nodes}
    accepted: list[GeneratedQuestion] = []
    budget = _child_slot_budget(parent, existing_nodes, limits)
    for draft in proposed:
        text = " ".join(draft.question.split())
        key = normalize_research_question(text)
        if not text:
            pre_filtered.append({"question": draft.question, "reason": "empty"})
            continue
        if key in known or key in ancestor_ids:
            pre_filtered.append({"question": text, "reason": "duplicate"})
            continue
        if apply_child_budget and len(accepted) >= budget:
            pre_filtered.append({"question": text, "reason": "child_budget"})
            continue
        known.add(key)
        accepted.append(GeneratedQuestion(question=text, why_needed=draft.why_needed.strip()))
    return accepted, pre_filtered


def _rejection_counts(rejections: Sequence[dict[str, str]]) -> dict[str, int]:
    counts = {key: 0 for key in _REJECTION_COUNT_KEYS}
    for item in rejections:
        reason = item.get("reason") or "no_semantic_progress"
        if reason in {"not_distinct_knowledge_need", "insufficient_semantic_progress"}:
            reason = "no_semantic_progress"
        if reason not in counts:
            reason = "no_semantic_progress"
        counts[reason] += 1
    return counts


def _exhaustion_reason(kept_count: int) -> str:
    if kept_count == 1:
        return "insufficient_distinct_children"
    return "no_semantic_progress"


def _note_tree_metric(tree: RecursiveQuestionTree, kind: str) -> None:
    if current_research_stats() is None:
        tree._queued_metrics.append(kind)
        return
    _apply_tree_metric(kind)


def drain_question_tree_metrics(tree: RecursiveQuestionTree) -> None:
    """Apply metrics recorded before the research stats scope was bound."""
    queued = tree._queued_metrics
    tree._queued_metrics = []
    for kind in queued:
        _apply_tree_metric(kind)


def _apply_tree_metric(kind: str) -> None:
    if kind == "decomposition_exhausted":
        record_decomposition_exhausted(redundancy=False)
    elif kind == "decomposition_exhausted_redundancy":
        record_decomposition_exhausted(redundancy=True)
    elif kind in {"started", "sufficient", "insufficient", "failed"}:
        record_research_fallback(kind)


def _child_filter_payload(
    *,
    candidate_count: int,
    accepted_count: int,
    rejections: list[dict[str, str]],
    pre_filtered: list[dict[str, str]],
    decomposition_decision: str,
) -> dict[str, object]:
    return {
        "candidate_count": candidate_count,
        "accepted_count": accepted_count,
        "rejected_count": len(rejections),
        "rejection_questions": [item["question"] for item in rejections],
        "rejection_reasons": [item["reason"] for item in rejections],
        "pre_filtered_count": len(pre_filtered),
        "pre_filtered_questions": [item["question"] for item in pre_filtered],
        "pre_filtered_reasons": [item["reason"] for item in pre_filtered],
        "decomposition_decision": decomposition_decision,
    }


def _ancestor_questions(
    parent: ResearchQuestionNode, existing_nodes: Sequence[ResearchQuestionNode]
) -> list[str]:
    """Questions above the parent. The parent itself is compared separately."""
    by_id = {row.id: row for row in existing_nodes}
    cursor = by_id.get(parent.parent_question_id or "")
    ancestors: list[str] = []
    while cursor is not None:
        ancestors.append(cursor.question)
        cursor = by_id.get(cursor.parent_question_id or "")
    return ancestors


async def append_answer_version(
    session: AsyncSession,
    *,
    node: ResearchQuestionNode,
    answer_text: str,
    status: AnswerStatus,
    child_answer_ids: Sequence[str] = (),
    evidence_items: Sequence[EvidenceSetItem] = (),
) -> tuple[ResearchQuestionAnswer, bool]:
    """Append only for materially new text or direct provenance."""
    text = answer_text.strip()
    child_ids = tuple(sorted(set(child_answer_ids)))
    evidence_ids = tuple(sorted({item.id for item in evidence_items}))
    current = (
        await session.get(ResearchQuestionAnswer, node.current_answer_id)
        if node.current_answer_id
        else None
    )
    if current is not None:
        current_children = tuple(
            sorted(
                (
                    await session.execute(
                        select(ResearchAnswerChildLink.child_answer_id).where(
                            ResearchAnswerChildLink.answer_id == current.id
                        )
                    )
                ).scalars()
            )
        )
        current_evidence = tuple(
            sorted(
                (
                    await session.execute(
                        select(ResearchAnswerEvidenceLink.evidence_set_item_id).where(
                            ResearchAnswerEvidenceLink.answer_id == current.id
                        )
                    )
                ).scalars()
            )
        )
        if (
            current.answer_text == text
            and current_children == child_ids
            and current_evidence == evidence_ids
        ):
            return current, False
    version = (
        int(
            (
                await session.execute(
                    select(func.max(ResearchQuestionAnswer.version)).where(
                        ResearchQuestionAnswer.question_node_id == node.id
                    )
                )
            ).scalar_one_or_none()
            or 0
        )
        + 1
    )
    answer = ResearchQuestionAnswer(
        id=_id(),
        question_node_id=node.id,
        supersedes_answer_id=current.id if current else None,
        version=version,
        status=status,
        answer_text=text,
    )
    session.add(answer)
    await session.flush()
    for child_id in child_ids:
        session.add(
            ResearchAnswerChildLink(
                id=_id(),
                answer_id=answer.id,
                child_answer_id=child_id,
            )
        )
    for item in evidence_items:
        session.add(
            ResearchAnswerEvidenceLink(
                id=_id(),
                answer_id=answer.id,
                evidence_set_item_id=item.id,
                passage_id=item.passage_id,
            )
        )
    node.current_answer_id = answer.id
    await session.flush()
    return answer, True


class RecursiveQuestionTree:
    def __init__(
        self,
        *,
        controller: QuestionTreeController,
        generator: QuestionTreeGenerator,
        limits: QuestionTreeLimits,
        source_types: Sequence[ResearchSourceType],
    ) -> None:
        self.controller = controller
        self.generator = generator
        self.limits = limits
        self.source_types = list(source_types)
        self.early_parent_synthesis_count = 0
        self._security_scope: str | None = None
        self._queued_metrics: list[str] = []

    async def prepare_leaf_plan(
        self,
        session: AsyncSession,
        *,
        attempt_id: str,
        root_question: str,
    ) -> ResearchPlan:
        with ProgressTracker() as progress:
            root = await get_or_create_root(session, attempt_id=attempt_id, question=root_question)
            await session.commit()
            await progress.publish_committed()
        await self._expand_pending(session, root)
        await self._log_shape(session, attempt_id, suffix="prepare")
        nodes = await list_question_nodes(session, attempt_id)
        needs: list[ResearchNeed] = []
        for node in nodes:
            if not _is_retrieval_leaf(node):
                continue
            need_id = node.research_need_id or f"question-{node.id}"
            node.research_need_id = need_id
            needs.append(
                self._research_need(node, why_needed="Retrieval leaf in the question tree.")
            )
        await session.commit()
        return ResearchPlan(needs=needs)

    @asynccontextmanager
    async def _bound_jev(self, session: AsyncSession, attempt_id: str) -> AsyncIterator[None]:
        scope = await self._security_scope_for(session, attempt_id)
        if scope is None:
            yield
            return
        with jev_evaluation_binding(session, scope):
            yield

    async def _security_scope_for(self, session: AsyncSession, attempt_id: str) -> str | None:
        if self._security_scope is not None:
            return self._security_scope
        customer_id = await session.scalar(
            select(ExecutionRun.customer_id)
            .join(ExecutionAttempt, ExecutionAttempt.run_id == ExecutionRun.id)
            .where(ExecutionAttempt.id == attempt_id)
        )
        if customer_id is None:
            return None
        self._security_scope = customer_scope_key(int(customer_id))
        return self._security_scope

    def _research_need(self, node: ResearchQuestionNode, *, why_needed: str) -> ResearchNeed:
        fallback = _is_best_effort(node)
        return ResearchNeed(
            id=node.research_need_id or f"question-{node.id}",
            question=node.question,
            why_needed=(
                "Best-effort retrieval after decomposition exhaustion." if fallback else why_needed
            ),
            source_types=list(self.source_types),
            generated_from="decomposition_fallback" if fallback else "",
        )

    async def _expand_pending(self, session: AsyncSession, node: ResearchQuestionNode) -> None:
        if node.decomposition_result == "exhausted":
            return
        if node.phase == "unresolved":
            return
        if node.researchability == "pending":
            await self._assess_structure(session, node)
        if node.phase in {"ready", "unresolved"}:
            return
        children = await self._children(session, node.id)
        if not children:
            if node.depth >= self.limits.max_depth:
                await self._stop_at_max_depth(session, node)
                return
            await self._decompose_node(session, node)
            if node.phase in {"ready", "unresolved"}:
                return
            children = await self._children(session, node.id)
        for child in children:
            await self._expand_pending(session, child)

    async def _assess_structure(self, session: AsyncSession, node: ResearchQuestionNode) -> None:
        with ProgressTracker() as progress:
            node.phase = "assessing_atomicity"
            await emit_question_event(session, node, "question_atomicity_started", suffix="started")
            await session.commit()
            await progress.publish_committed()
        async with self._bound_jev(session, node.attempt_id):
            decision = await self.controller.assess_structure(question=node.question)
        action = structure_action(decision.researchability, decision.decomposability)
        with ProgressTracker() as progress:
            node.researchability = decision.researchability
            node.decomposability = decision.decomposability
            node.researchability_noul = _signal_subset(decision.noul, _RESEARCHABILITY_SIGNALS)
            node.decomposability_noul = _signal_subset(decision.noul, _DECOMPOSABILITY_SIGNALS)
            node.atomicity_noul = dict(decision.noul)
            if action == "retrieve":
                node.phase = "ready"
            elif action == "decompose":
                node.phase = "created"
            else:
                node.phase = "unresolved"
            noul = dict(decision.noul)
            await emit_question_event(
                session,
                node,
                "question_atomicity_completed",
                suffix="completed",
                researchable=decision.researchability == "researchable",
                decomposable=decision.decomposability == "decomposable",
                researchability={
                    "decision": decision.researchability,
                    "reason": decision.researchability_reason,
                    "confidence": decision.researchability_confidence,
                },
                decomposability={
                    "decision": decision.decomposability,
                    "reason": decision.decomposability_reason,
                    "confidence": decision.decomposability_confidence,
                },
                action=action,
                thresholds={"structure": decision.threshold},
                **noul,
                noul=noul,
                **_question_payload(decision, step="question_structure"),
            )
            await session.commit()
            await progress.publish_committed()

    async def _stop_at_max_depth(self, session: AsyncSession, node: ResearchQuestionNode) -> None:
        researchable = node.researchability == "researchable"
        with ProgressTracker() as progress:
            node.phase = "ready" if researchable else "unresolved"
            await emit_question_event(
                session,
                node,
                "question_tree_max_depth_reached",
                suffix="max-depth",
                question=node.question,
                reason="max_depth",
                fallback="research_parent" if researchable else "unresolved",
                researchability=node.researchability,
                decomposability=node.decomposability,
                researchability_noul=dict(node.researchability_noul or {}),
                decomposability_noul=dict(node.decomposability_noul or {}),
            )
            await session.commit()
            await progress.publish_committed()

    async def _decompose_node(self, session: AsyncSession, node: ResearchQuestionNode) -> None:
        with ProgressTracker() as progress:
            node.phase = "decomposing"
            await emit_question_event(
                session, node, "question_decomposition_started", suffix="started"
            )
            await session.commit()
            await progress.publish_committed()
        started = time.perf_counter()
        proposed = await self.generator.decompose(question=node.question)
        duration_ms = (time.perf_counter() - started) * 1000
        provider = str(getattr(self.generator, "model_provider", "llm"))
        model = str(getattr(self.generator, "model", ""))
        record_question_step(
            "decomposition",
            duration_ms=duration_ms,
            model_provider=provider,
            model=model,
        )
        all_nodes = await list_question_nodes(session, node.attempt_id)
        structural, pre_filtered = _validated_questions(
            parent=node,
            proposed=proposed,
            existing_nodes=all_nodes,
            limits=self.limits,
            apply_child_budget=False,
        )
        kept, rejections, held = await self._drop_redundant_children(
            session,
            parent=node,
            proposed=structural,
            existing_nodes=all_nodes,
            budget=_child_slot_budget(node, all_nodes, self.limits),
        )
        pre_filtered.extend(held)
        validation: DecompositionDecision | None = None
        if len(kept) >= 2:
            async with self._bound_jev(session, node.attempt_id):
                validation = await self.controller.validate_decomposition(
                    question=node.question,
                    children=[item.question for item in kept],
                )
            record_question_step(
                "decomposition_validation",
                duration_ms=validation.duration_ms,
                model_provider=validation.model_provider,
                model=validation.model,
            )
            if validation.accepted:
                await self._accept_decomposition(
                    session,
                    node,
                    children=kept,
                    rejections=rejections,
                    pre_filtered=pre_filtered,
                    candidate_count=len(proposed),
                    duration_ms=duration_ms,
                    model_provider=provider,
                    model=model,
                    validation=validation,
                )
                return
        await self._exhaust_decomposition(
            session,
            node,
            kept_count=len(kept),
            duration_ms=duration_ms,
            model_provider=provider,
            model=model,
            validation=validation,
            candidate_count=len(proposed),
            rejections=rejections,
            pre_filtered=pre_filtered,
        )

    async def _drop_redundant_children(
        self,
        session: AsyncSession,
        *,
        parent: ResearchQuestionNode,
        proposed: Sequence[GeneratedQuestion],
        existing_nodes: Sequence[ResearchQuestionNode],
        budget: int,
    ) -> tuple[list[GeneratedQuestion], list[dict[str, str]], list[dict[str, str]]]:
        """Keep a proper substantive subset. Stop once the child budget is full."""
        ancestors = _ancestor_questions(parent, existing_nodes)
        kept: list[GeneratedQuestion] = []
        rejections: list[dict[str, str]] = []
        held: list[dict[str, str]] = []
        for draft in proposed:
            if len(kept) >= budget:
                held.append({"question": draft.question, "reason": "child_budget"})
                continue
            async with self._bound_jev(session, parent.attempt_id):
                decision = await self.controller.validate_child_redundancy(
                    parent=parent.question,
                    candidate=draft.question,
                    siblings=[item.question for item in kept],
                    ancestors=ancestors,
                )
            record_question_step(
                "child_redundancy",
                duration_ms=decision.duration_ms,
                model_provider=decision.model_provider,
                model=decision.model,
            )
            if decision.accepted:
                kept.append(draft)
                continue
            rejections.append(
                {
                    "question": draft.question,
                    "reason": decision.rejection_reason or "not_distinct_knowledge_need",
                }
            )
        return kept, rejections, held

    async def _accept_decomposition(
        self,
        session: AsyncSession,
        node: ResearchQuestionNode,
        *,
        children: Sequence[GeneratedQuestion],
        rejections: list[dict[str, str]],
        pre_filtered: list[dict[str, str]],
        candidate_count: int,
        duration_ms: float,
        model_provider: str,
        model: str,
        validation: DecompositionDecision,
    ) -> None:
        with ProgressTracker() as progress:
            for draft in children:
                child = ResearchQuestionNode(
                    id=_id(),
                    attempt_id=node.attempt_id,
                    parent_question_id=node.id,
                    question=draft.question,
                    depth=node.depth + 1,
                    created_from="decomposition",
                    phase="created",
                    atomicity="pending",
                    researchability="pending",
                    decomposability="pending",
                )
                session.add(child)
                await session.flush()
                await emit_question_event(
                    session, child, "question_created", suffix="decomposition"
                )
            node.decomposition_result = "accepted"
            node.phase = "decomposed"
            await emit_question_event(
                session,
                node,
                "question_decomposed",
                suffix="completed",
                child_count=len(children),
                duration_ms=duration_ms,
                model_provider=model_provider,
                model=model,
                validation=_validation_scores(validation),
                decision="accepted",
                rejection_reason="",
                validation_duration_ms=validation.duration_ms,
                validation_model_provider=validation.model_provider,
                validation_model=validation.model,
                **_child_filter_payload(
                    candidate_count=candidate_count,
                    accepted_count=len(children),
                    rejections=rejections,
                    pre_filtered=pre_filtered,
                    decomposition_decision="accepted",
                ),
            )
            await session.commit()
            await progress.publish_committed()

    async def _exhaust_decomposition(
        self,
        session: AsyncSession,
        node: ResearchQuestionNode,
        *,
        kept_count: int,
        duration_ms: float,
        model_provider: str,
        model: str,
        validation: DecompositionDecision | None,
        candidate_count: int,
        rejections: list[dict[str, str]],
        pre_filtered: list[dict[str, str]],
    ) -> None:
        """Stop splitting and research this question. Researchability stays as scored."""
        reason = _exhaustion_reason(kept_count)
        counts = _rejection_counts(rejections)
        redundancy = any(counts[key] for key in _REDUNDANCY_REASONS)
        if kept_count == 0:
            decomposition_decision = "no_valid_children"
        elif kept_count == 1:
            decomposition_decision = "insufficient_distinct_children"
        else:
            decomposition_decision = "insufficient_semantic_progress"
        node.decomposition_result = "exhausted"
        node.execution_override = "best_effort_retrieval"
        node.execution_override_reason = reason
        node.phase = "ready"
        _note_tree_metric(
            self,
            "decomposition_exhausted_redundancy" if redundancy else "decomposition_exhausted",
        )
        _note_tree_metric(self, "started")
        logger.info(
            "decomposition exhausted question_id=%s depth=%s generated_child_count=%s "
            "accepted_child_count=%s rejection_counts=%s fallback_action=best_effort_retrieval",
            node.id,
            node.depth,
            candidate_count,
            kept_count,
            counts,
        )
        with ProgressTracker() as progress:
            await emit_question_event(
                session,
                node,
                "question_decomposed",
                suffix="completed",
                child_count=kept_count,
                duration_ms=duration_ms,
                model_provider=model_provider,
                model=model,
                validation=_validation_scores(validation),
                decision="rejected",
                rejection_reason=reason,
                fallback="best_effort_retrieval",
                decomposition_result="exhausted",
                execution_override="best_effort_retrieval",
                execution_override_reason=reason,
                generated_child_count=candidate_count,
                accepted_child_count=kept_count,
                rejection_counts=counts,
                validation_duration_ms=0.0 if validation is None else validation.duration_ms,
                validation_model_provider="" if validation is None else validation.model_provider,
                validation_model="" if validation is None else validation.model,
                **_child_filter_payload(
                    candidate_count=candidate_count,
                    accepted_count=kept_count,
                    rejections=rejections,
                    pre_filtered=pre_filtered,
                    decomposition_decision=decomposition_decision,
                ),
            )
            await session.commit()
            await progress.publish_committed()

    async def _children(self, session: AsyncSession, parent_id: str) -> list[ResearchQuestionNode]:
        result = await session.execute(
            select(ResearchQuestionNode)
            .where(ResearchQuestionNode.parent_question_id == parent_id)
            .order_by(ResearchQuestionNode.created_at, ResearchQuestionNode.id)
        )
        return list(result.scalars())

    async def synthesize_wave(
        self,
        session: AsyncSession,
        *,
        attempt_id: str,
        evidence_set_id: str,
    ) -> ResearchPlan:
        """Create material answer versions bottom-up and return newly exposed leaves.

        Siblings are still synthesized in depth order. A later frontier scheduler
        should synthesize a parent when its children are ready, including while
        another branch is still researching. Readiness decides that, not walk order.
        """
        nodes = await list_question_nodes(session, attempt_id)
        runtime_rows = list(
            (
                await session.execute(
                    select(ResearchRuntimeNeed).where(ResearchRuntimeNeed.attempt_id == attempt_id)
                )
            ).scalars()
        )
        runtime_by_need = {row.research_need_id: row for row in runtime_rows}
        for node in nodes:
            runtime = runtime_by_need.get(node.research_need_id or "")
            if runtime is not None and runtime.knowledge_question_id:
                node.knowledge_question_id = runtime.knowledge_question_id
        evidence_by_need = await _evidence_by_need(session, evidence_set_id)
        for node in sorted(nodes, key=lambda row: row.depth, reverse=True):
            if _is_retrieval_leaf(node):
                await self._synthesize_leaf(session, node, evidence_by_need)
            else:
                await self._synthesize_parent(session, node)
        nodes = await list_question_nodes(session, attempt_id)
        existing_need_ids = {row.research_need_id for row in runtime_rows}
        needs = []
        for node in nodes:
            if node.phase in {"not_required", "unresolved", "failed", "decomposed"}:
                continue
            if node.current_answer_id is not None:
                continue
            if node.researchability != "researchable" and not _is_best_effort(node):
                continue
            if node.phase != "ready" and not node.research_need_id:
                continue
            if not node.research_need_id:
                node.research_need_id = f"question-{node.id}"
            if node.research_need_id in existing_need_ids:
                continue
            needs.append(
                self._research_need(
                    node,
                    why_needed="Gap-driven retrieval leaf in the question tree.",
                )
            )
        await session.flush()
        await self._log_shape(session, attempt_id, suffix="synthesize")
        return ResearchPlan(needs=needs)

    async def _synthesize_leaf(
        self,
        session: AsyncSession,
        node: ResearchQuestionNode,
        evidence_by_need: dict[str, list[EvidenceSetItem]],
    ) -> None:
        items = evidence_by_need.get(node.research_need_id or "", [])
        if node.current_answer_id and await _direct_provenance_matches(
            session,
            node.current_answer_id,
            evidence_ids=[item.id for item in items],
        ):
            return
        with ProgressTracker() as progress:
            node.phase = "synthesizing"
            await emit_question_event(
                session, node, "answer_synthesis_started", suffix="leaf-started"
            )
            await session.commit()
            await progress.publish_committed()
        try:
            generated = await self.generator.synthesize_leaf(
                question=node.question,
                evidence=items,
            )
        except Exception:
            if _is_best_effort(node):
                _note_tree_metric(self, "failed")
            raise
        if _is_best_effort(node) and node.researchability != "researchable":
            _record_fallback_answer(node, generated.status)
        with ProgressTracker() as progress:
            answer, created = await append_answer_version(
                session,
                node=node,
                answer_text=generated.text,
                status=generated.status,
                evidence_items=items,
            )
            node.phase = (
                "evidence_incomplete"
                if generated.status == "insufficient_evidence"
                else "completed"
            )
            node.completeness = (
                "insufficient" if generated.status == "insufficient_evidence" else generated.status
            )
            await emit_question_event(
                session,
                node,
                "answer_synthesized",
                suffix=f"leaf:{answer.id}",
                answer_id=answer.id,
                answer_version=answer.version,
                version_created=created,
                answer_status=answer.status,
                **_question_payload(generated, step="leaf_synthesis"),
            )
            await emit_question_event(
                session,
                node,
                "question_completed",
                suffix=f"leaf:{answer.id}",
                answer_id=answer.id,
                answer_status=answer.status,
            )
            await session.commit()
            await progress.publish_committed()

    async def _synthesize_parent(
        self,
        session: AsyncSession,
        node: ResearchQuestionNode,
    ) -> None:
        children = await self._children(session, node.id)
        inputs = await _answer_inputs(session, children)
        if not children or not inputs:
            return
        if node.current_answer_id and await _direct_provenance_matches(
            session,
            node.current_answer_id,
            child_answer_ids=[item.answer_id for item in inputs],
        ):
            return
        async with self._bound_jev(session, node.attempt_id):
            readiness = await self.controller.assess_synthesis_readiness(
                question=node.question,
                child_answers=inputs,
            )
        node.synthesis_readiness_noul = dict(readiness.noul)
        if not readiness.sufficient:
            await session.commit()
            return
        if await _has_unfinished_descendant(session, node):
            self.early_parent_synthesis_count += 1
        with ProgressTracker() as progress:
            node.phase = "synthesizing"
            await emit_question_event(
                session,
                node,
                "answer_synthesis_started",
                suffix=f"parent:{','.join(item.answer_id for item in inputs)}",
                **_question_payload(readiness, step="synthesis_readiness"),
            )
            await session.commit()
            await progress.publish_committed()
        generated = await self.generator.synthesize_parent(
            question=node.question,
            child_answers=inputs,
        )
        with ProgressTracker() as progress:
            answer, created = await append_answer_version(
                session,
                node=node,
                answer_text=generated.text,
                status=generated.status,
                child_answer_ids=[item.answer_id for item in inputs],
            )
            node.phase = "assessing_completeness"
            await emit_question_event(
                session,
                node,
                "answer_synthesized",
                suffix=f"parent:{answer.id}",
                answer_id=answer.id,
                answer_version=answer.version,
                version_created=created,
                answer_status=answer.status,
                **_question_payload(generated, step="parent_synthesis"),
            )
            await emit_question_event(
                session,
                node,
                "question_completeness_started",
                suffix=f"parent:{answer.id}",
            )
            await session.commit()
            await progress.publish_committed()
        completeness_inputs = await _completeness_child_inputs(session, children)
        async with self._bound_jev(session, node.attempt_id):
            completeness = await self.controller.assess_completeness(
                question=node.question,
                answer=answer.answer_text,
                child_answers=completeness_inputs,
            )
        with ProgressTracker() as progress:
            node.completeness = completeness.status
            node.completeness_noul = dict(completeness.noul)
            node.phase = "completed"
            await emit_question_event(
                session,
                node,
                "question_completeness_completed",
                suffix=f"parent:{answer.id}",
                completeness=completeness.status,
                **_question_payload(completeness, step="completeness"),
            )
            await session.commit()
            await progress.publish_committed()
        if completeness.material_gap and completeness.additional_research_likely_to_change_answer:
            await self._expand_gap(session, node, answer, inputs, completeness)
        else:
            with ProgressTracker() as progress:
                await emit_question_event(
                    session,
                    node,
                    "question_completed",
                    suffix=f"parent:{answer.id}",
                    answer_id=answer.id,
                    completeness=completeness.status,
                )
                await session.commit()
                await progress.publish_committed()
            await self._retire_unneeded_descendants(session, node)

    async def _retire_unneeded_descendants(
        self,
        session: AsyncSession,
        node: ResearchQuestionNode,
    ) -> None:
        nodes = await list_question_nodes(session, node.attempt_id)
        children_by_parent: dict[str | None, list[ResearchQuestionNode]] = {}
        for row in nodes:
            children_by_parent.setdefault(row.parent_question_id, []).append(row)
        pending = list(children_by_parent.get(node.id, []))
        retired: list[ResearchQuestionNode] = []
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current.id in seen:
                continue
            seen.add(current.id)
            pending.extend(children_by_parent.get(current.id, []))
            if current.current_answer_id is not None or current.phase not in _RETIRABLE_PHASES:
                continue
            current.phase = "not_required"
            retired.append(current)
        if not retired:
            return
        with ProgressTracker() as progress:
            for current in retired:
                await emit_question_event(
                    session,
                    current,
                    "question_completed",
                    suffix="not-required",
                    reason="not_required",
                )
            await session.commit()
            await progress.publish_committed()

    async def _log_shape(self, session: AsyncSession, attempt_id: str, *, suffix: str) -> None:
        nodes = await list_question_nodes(session, attempt_id)
        if not nodes:
            return
        root = next(node for node in nodes if node.parent_question_id is None)
        shape = _question_tree_shape(
            nodes,
            early_parent_synthesis_count=self.early_parent_synthesis_count,
        )
        record_question_outcome_counts(
            unresolved_required=int(shape["unresolved_required_question_count"]),
            not_required=int(shape["not_required_question_count"]),
        )
        with ProgressTracker() as progress:
            await emit_question_event(
                session,
                root,
                "question_tree_shape",
                suffix=suffix,
                **shape,
            )
            await session.commit()
            await progress.publish_committed()

    async def _expand_gap(
        self,
        session: AsyncSession,
        node: ResearchQuestionNode,
        answer: ResearchQuestionAnswer,
        inputs: Sequence[AnswerInput],
        completeness: CompletenessDecision,
    ) -> None:
        existing_gap_children = [
            child for child in await self._children(session, node.id) if child.created_from == "gap"
        ]
        if existing_gap_children and any(
            child.current_answer_id is None for child in existing_gap_children
        ):
            return
        started = time.perf_counter()
        proposed = await self.generator.formulate_gap_questions(
            question=node.question,
            answer=answer.answer_text,
            child_answers=inputs,
            gap_noul=dict(completeness.noul),
        )
        duration_ms = (time.perf_counter() - started) * 1000
        record_question_step(
            "gap_formulation",
            duration_ms=duration_ms,
            model_provider=str(getattr(self.generator, "model_provider", "llm")),
            model=str(getattr(self.generator, "model", "")),
        )
        all_nodes = await list_question_nodes(session, node.attempt_id)
        accepted, _pre_filtered = _validated_questions(
            parent=node,
            proposed=proposed,
            existing_nodes=all_nodes,
            limits=self.limits,
        )
        if not accepted:
            return
        with ProgressTracker() as progress:
            for draft in accepted:
                child = ResearchQuestionNode(
                    id=_id(),
                    attempt_id=node.attempt_id,
                    parent_question_id=node.id,
                    question=draft.question,
                    depth=node.depth + 1,
                    created_from="gap",
                    phase="created",
                    atomicity="pending",
                    researchability="pending",
                    decomposability="pending",
                )
                session.add(child)
                await session.flush()
                await emit_question_event(
                    session, child, "question_created", suffix=f"gap:{answer.id}"
                )
            node.phase = "decomposed"
            await emit_question_event(
                session,
                node,
                "question_gap_detected",
                suffix=f"answer:{answer.id}",
                child_count=len(accepted),
                duration_ms=duration_ms,
                model_provider=str(getattr(self.generator, "model_provider", "llm")),
                model=str(getattr(self.generator, "model", "")),
            )
            await session.commit()
            await progress.publish_committed()
        for child in await self._children(session, node.id):
            if child.created_from == "gap" and child.researchability == "pending":
                await self._expand_pending(session, child)


async def _has_unfinished_descendant(
    session: AsyncSession,
    node: ResearchQuestionNode,
) -> bool:
    nodes = await list_question_nodes(session, node.attempt_id)
    children_by_parent: dict[str | None, list[ResearchQuestionNode]] = {}
    for row in nodes:
        children_by_parent.setdefault(row.parent_question_id, []).append(row)
    pending = list(children_by_parent.get(node.id, []))
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current.id in seen:
            continue
        seen.add(current.id)
        pending.extend(children_by_parent.get(current.id, []))
        if current.current_answer_id is None and current.phase != "failed":
            return True
    return False


def _question_tree_shape(
    nodes: Sequence[ResearchQuestionNode],
    *,
    early_parent_synthesis_count: int,
) -> dict[str, object]:
    children_by_parent: dict[str | None, list[ResearchQuestionNode]] = {}
    questions_by_depth: dict[str, int] = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_question_id, []).append(node)
        key = f"depth_{node.depth}"
        questions_by_depth[key] = questions_by_depth.get(key, 0) + 1
    decomposable_nodes = [node for node in nodes if node.decomposability == "decomposable"]
    child_counts = [len(children_by_parent.get(node.id, [])) for node in decomposable_nodes]
    split_counts = [count for count in child_counts if count]
    leaves = [node for node in nodes if _is_retrieval_leaf(node)]
    researchable_nodes = [node for node in nodes if node.researchability == "researchable"]
    answered_leaves = [
        node
        for node in leaves
        if node.current_answer_id is not None and node.completeness == "answered"
    ]
    insufficient_leaves = [
        node
        for node in leaves
        if node.phase == "evidence_incomplete" or node.completeness == "insufficient"
    ]
    parents_with_answers = [
        node for node in decomposable_nodes if node.current_answer_id is not None
    ]
    return {
        "question_count": len(nodes),
        "leaf_count": len(leaves),
        "decomposable_count": len(decomposable_nodes),
        "researchable_count": len(researchable_nodes),
        "researchable_and_decomposable_count": sum(
            1
            for node in nodes
            if node.researchability == "researchable" and node.decomposability == "decomposable"
        ),
        "composite_count": len(decomposable_nodes),
        "max_depth_reached": max(node.depth for node in nodes),
        "questions_by_depth": questions_by_depth,
        "decomposition_count": sum(
            1 for node in decomposable_nodes if children_by_parent.get(node.id)
        ),
        "average_children_per_composite": (
            sum(split_counts) / len(split_counts) if split_counts else 0
        ),
        "max_children": max(child_counts, default=0),
        "researched_leaf_count": sum(1 for node in leaves if node.research_need_id),
        "answered_leaf_count": len(answered_leaves),
        "insufficient_leaf_count": len(insufficient_leaves),
        "unresolved_count": sum(1 for node in nodes if node.phase == "unresolved"),
        "not_required_count": sum(1 for node in nodes if node.phase == "not_required"),
        **knowledge_need_counts(nodes),
        "failed_count": sum(1 for node in nodes if node.phase == "failed"),
        "parent_synthesis_count": len(parents_with_answers),
        "early_parent_synthesis_count": early_parent_synthesis_count,
    }


def _record_fallback_answer(node: ResearchQuestionNode, status: str) -> None:
    if status == "answered":
        _note_tree_metric_unscoped("sufficient")
        logger.info(
            "researchability_false_negative question_id=%s depth=%s answer_status=%s",
            node.id,
            node.depth,
            status,
        )
        return
    if status == "insufficient_evidence":
        _note_tree_metric_unscoped("insufficient")


def _note_tree_metric_unscoped(kind: str) -> None:
    """Fallback outcomes happen after stats are bound. Queue only if they are not."""
    if current_research_stats() is None:
        return
    _apply_tree_metric(kind)


_TERMINAL_CHILD_ANSWER = {
    "not_required": "This branch was not required for the parent answer.",
    "failed": "Technical failure. No grounded answer.",
    "unresolved": "No grounded answer.",
}


def _terminal_child_status(child: ResearchQuestionNode) -> str | None:
    if child.phase == "not_required":
        return "not_required"
    if child.phase == "failed":
        return "failed"
    if child.current_answer_id is not None:
        return None
    if child.phase in {"unresolved", "evidence_incomplete"}:
        return "unresolved"
    return None


async def _completeness_child_inputs(
    session: AsyncSession,
    children: Sequence[ResearchQuestionNode],
) -> list[AnswerInput]:
    """Answered children plus terminal siblings that still have no grounded answer."""
    answered = await _answer_inputs(session, children)
    seen = {item.question for item in answered}
    extras: list[AnswerInput] = []
    for child in children:
        if child.question in seen:
            continue
        status = _terminal_child_status(child)
        if status is None:
            continue
        extras.append(
            AnswerInput(
                answer_id=child.current_answer_id or child.id,
                question=child.question,
                answer=_TERMINAL_CHILD_ANSWER[status],
                status=status,
            )
        )
    return [*answered, *extras]


async def settle_stranded_question_nodes(session: AsyncSession, *, attempt_id: str) -> None:
    """A finished attempt must not leave a required question waiting with no answer."""
    nodes = await list_question_nodes(session, attempt_id)
    stranded = [
        node
        for node in nodes
        if node.current_answer_id is None and node.phase not in _TERMINAL_QUESTION_PHASES
    ]
    if not stranded:
        _record_knowledge_need_counts(nodes)
        return
    for node in stranded:
        node.phase = "unresolved"
    with ProgressTracker() as progress:
        for node in stranded:
            await emit_question_event(
                session,
                node,
                "question_completed",
                suffix="unresolved",
                reason="unresolved",
            )
        await session.commit()
        await progress.publish_committed()
    _record_knowledge_need_counts(nodes)


async def _answer_inputs(
    session: AsyncSession,
    children: Sequence[ResearchQuestionNode],
) -> list[AnswerInput]:
    inputs = []
    for child in children:
        if child.current_answer_id is None:
            continue
        answer = await session.get(ResearchQuestionAnswer, child.current_answer_id)
        if answer is None:
            continue
        inputs.append(
            AnswerInput(
                answer_id=answer.id,
                question=child.question,
                answer=answer.answer_text,
                status=answer.status,
            )
        )
    return inputs


async def _direct_provenance_matches(
    session: AsyncSession,
    answer_id: str,
    *,
    child_answer_ids: Sequence[str] = (),
    evidence_ids: Sequence[str] = (),
) -> bool:
    stored_children = set(
        (
            await session.execute(
                select(ResearchAnswerChildLink.child_answer_id).where(
                    ResearchAnswerChildLink.answer_id == answer_id
                )
            )
        ).scalars()
    )
    stored_evidence = set(
        (
            await session.execute(
                select(ResearchAnswerEvidenceLink.evidence_set_item_id).where(
                    ResearchAnswerEvidenceLink.answer_id == answer_id
                )
            )
        ).scalars()
    )
    return stored_children == set(child_answer_ids) and stored_evidence == set(evidence_ids)


async def _evidence_by_need(
    session: AsyncSession, evidence_set_id: str
) -> dict[str, list[EvidenceSetItem]]:
    items = list(
        (
            await session.execute(
                select(EvidenceSetItem)
                .where(EvidenceSetItem.evidence_set_id == evidence_set_id)
                .order_by(EvidenceSetItem.ordinal, EvidenceSetItem.id)
            )
        ).scalars()
    )
    links = (
        list(
            (
                await session.execute(
                    select(EvidenceSetItemNeed).where(
                        EvidenceSetItemNeed.evidence_set_item_id.in_([item.id for item in items])
                    )
                )
            ).scalars()
        )
        if items
        else []
    )
    need_ids: dict[str, set[str]] = {}
    for link in links:
        need_ids.setdefault(link.evidence_set_item_id, set()).add(link.research_need_id)
    result: dict[str, list[EvidenceSetItem]] = {}
    for item in items:
        ids = need_ids.get(item.id, set())
        if item.research_need_id:
            ids.add(item.research_need_id)
        for need_id in ids:
            result.setdefault(need_id, []).append(item)
    return result
