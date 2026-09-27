"""Jev controller for recursive question-tree decisions."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from app.config import settings
from app.jev.evaluation import (
    EVALUATION_POLICY_V1,
    EVALUATOR_CHILD_REDUNDANCY,
    EVALUATOR_DECOMPOSITION_VALIDATION,
    EVALUATOR_QUESTION_COMPLETENESS,
    EVALUATOR_QUESTION_STRUCTURE,
    EVALUATOR_SYNTHESIS_READINESS,
    EVALUATOR_VERSION_V1,
    threshold_config,
)
from app.jev.service import evaluate_system_one
from app.jev.system import HttpJevSystemOne, JevSystemOne, parse_noul
from app.services.research.fast_controller import _noul_question, research_jev_model
from app.services.research.question_tree import (
    AnswerInput,
    ChildRedundancyDecision,
    CompletenessDecision,
    Decomposability,
    DecompositionDecision,
    ReadinessDecision,
    Researchability,
    StructureDecision,
)

RESEARCHABILITY_QUESTIONS = {
    "bounded_for_evidence_retrieval": _noul_question(
        "Can this question be sent to evidence retrieval as one bounded evidence need?",
        true="Yes. Retrieval can search for the sources this question asks for, "
        "including many matching objects.",
        false="No. The question mixes targets that one retrieval request cannot aim at.",
    ),
    "can_produce_grounded_answer": _noul_question(
        "Can retrieved evidence ground an answer to this question directly?",
        true="Yes. A definition, a mapping, or a synthesis can be grounded from "
        "what retrieval returns, even when that answer cites many sources.",
        false="No. An answer cannot be grounded until separate knowledge "
        "dimensions have their own evidence.",
    ),
}

DECOMPOSABILITY_QUESTIONS = {
    "robust_answer_requires_multiple_distinct_subconclusions": _noul_question(
        "Would a robust answer to this question naturally require multiple distinct "
        "substantive conclusions or knowledge components, rather than one conclusion "
        "or one mapping supported by multiple items?",
        true="Yes. The answer is built from several distinct substantive parts, "
        "such as which criteria govern the subject, which circumstances affect it, "
        "and which consequences follow. Those parts may all concern the same subject.",
        false="No. The answer is one conclusion or one mapping. Multiple sources, "
        "cases, studies, examples, factors, list items, observations, documents, "
        "citations, or supporting arguments are evidence or results, not extra "
        "conclusions. A long question can still be one mapping, and a short "
        "question can still need several parts. Question length does not decide this.",
    ),
    "subconclusions_can_be_researched_separately": _noul_question(
        "Could those distinct components reasonably be posed as separate research "
        "questions and each receive its own grounded answer? Separate does not "
        "mean unrelated: the subquestions may concern the same subject, doctrine, "
        "system, phenomenon, or parent concept.",
        true="Yes. Each component can be asked and grounded on its own while still "
        "being about the same subject as the parent.",
        false="No. The components cannot be grounded apart from one another, or a "
        "split would only restate the parent in more specific words. Positive and "
        "negative findings of the same component, such as when something applies "
        "and when it does not, stay one research question.",
    ),
    "subconclusions_would_be_useful_as_reusable_knowledge": _noul_question(
        "Would grounded answers to those components be useful beyond merely "
        "reconstructing this exact wording of the parent question?",
        true="Yes. A later question about the same subject could reuse a component "
        "answer, and the set can be synthesized back into the parent.",
        false="No. The split only reconstructs this wording, lists its evidence "
        "objects, or paraphrases the parent.",
    ),
}

STRUCTURE_QUESTIONS = {**RESEARCHABILITY_QUESTIONS, **DECOMPOSABILITY_QUESTIONS}

DECOMPOSITION_VALIDATION_QUESTIONS = {
    "independent": _noul_question(
        "Are the child questions separate knowledge needs, rather than restatements of one need?",
        true="Yes. Each child asks for knowledge the others do not.",
        false="No. They are the same need, or one only narrows the wording of another.",
    ),
    "narrower": _noul_question(
        "Is every child strictly narrower than the parent question?",
        true="Yes. Each child drops scope the parent still contains.",
        false="No. At least one child has the same scope as the parent.",
    ),
    "semantic_progress": _noul_question(
        "Do the children add semantic progress that can be synthesized back "
        "into the parent, rather than only refining its wording?",
        true="Yes. Answering the children supplies distinct parts of the parent.",
        false="No. The children are reformulations and do not split the "
        "parent's knowledge. A single child that only restates the parent "
        "adds no progress.",
    ),
    "paraphrase_risk": _noul_question(
        "Are the children simple paraphrases or serial refinements of the "
        "parent, including a single child that only restates it?",
        true="Yes. They rephrase the parent or enumerate its evidence objects "
        "instead of separating knowledge needs.",
        false="No. They are genuinely different and narrower knowledge needs.",
    ),
    "jointly_sufficient_or_useful": _noul_question(
        "Would grounded answers to these children together be useful for answering the parent?",
        true="Yes. The set can be synthesized back into the parent.",
        false="No. The children do not supply knowledge the parent needs.",
    ),
}

_SET_PROGRESS_SIGNALS = (
    "semantic_progress",
    "jointly_sufficient_or_useful",
)

CHILD_REDUNDANCY_QUESTIONS = {
    "same_knowledge_need_as_parent": _noul_question(
        "If the candidate were answered completely, would that answer the "
        "entire parent question? A proper substantive subset is not the same "
        "need. A paraphrase, or a narrower wording that still asks the whole "
        "parent, is the same need.",
        true="Yes. The candidate asks every part of the parent. A paraphrase "
        "counts. How versus which is the same need only when that wording "
        "still asks the whole question. When something applies and when it "
        "does not stay one need. A mapping of many results is one need, not "
        "a child per result.",
        false="No. Sharing the parent's subject is not the same need. A "
        "complete answer would leave a real part unanswered. One factor, one "
        "concept, one class, or one effect is a proper substantive subset. "
        "Asking what significance one part has, while the parent asks how "
        "the whole subject is handled, is that subset.",
    ),
    "same_knowledge_need_as_sibling": _noul_question(
        "Is the candidate the same knowledge need as a listed sibling? If no "
        "siblings are listed, this is false.",
        true="Yes. It restates a sibling, including as how versus which or as "
        "a wording that would answer that sibling entirely.",
        false="No. It asks for a distinct part none of the siblings ask for, "
        "or no siblings are listed.",
    ),
    "same_knowledge_need_as_ancestor": _noul_question(
        "Is the candidate the same knowledge need as a listed ancestor other "
        "than the parent? A proper substantive subset of an ancestor is "
        "allowed. If no ancestors are listed, this is false.",
        true="Yes. A complete answer would answer that ancestor entirely, "
        "including a paraphrase or reformulation of the ancestor's whole "
        "question.",
        false="No. The candidate is only a subset of an ancestor, no listed "
        "ancestor asks this same whole question, or no ancestors are listed.",
    ),
    "candidate_adds_distinct_subconclusion": _noul_question(
        "Would a grounded answer to the candidate supply a distinct "
        "substantive part of the parent, rather than answering the parent "
        "as a whole or restating a sibling or ancestor?",
        true="Yes. It is a proper substantive subset. Answering it covers one "
        "distinct part and leaves the rest of the parent open. The parent "
        "may already contain that part.",
        false="No. It answers the whole parent, paraphrases a need that is "
        "already represented, or adds no distinct part.",
    ),
    "candidate_is_narrower_but_substantively_distinct": _noul_question(
        "Is the candidate a proper substantive subset of the parent: narrower "
        "in scope, and a distinct part rather than a tighter wording of the "
        "whole question?",
        true="Yes. The dropped scope is a real part of the parent, and what "
        "remains is its own conclusion.",
        false="No. It still asks the whole parent, it is a paraphrase, or it is not narrower.",
    ),
}

READINESS_QUESTIONS = {
    "sufficient_to_answer_parent": _noul_question(
        "Are the child answers sufficient to answer the parent question?",
        true="A grounded parent answer can be synthesized now.",
        false="The available child answers do not cover the parent.",
    ),
    "material_gap_remains": _noul_question(
        "Does a material information gap remain?",
        true="The gap could materially affect the answer.",
        false="Remaining limitations are immaterial.",
    ),
    "additional_research_likely_to_change_answer": _noul_question(
        "Would additional research likely change the answer?",
        true="More research would materially change it.",
        false="More research is unlikely to change it.",
    ),
}


def classify_researchability(
    noul: Mapping[str, float], *, threshold: float
) -> tuple[Researchability, str, float]:
    """Whether one retrieval can ground an answer. This does not decide decomposition."""
    low = 1 - threshold
    bounded = noul["bounded_for_evidence_retrieval"]
    grounded = noul["can_produce_grounded_answer"]
    confidence = min(bounded, grounded)
    if bounded >= threshold and grounded >= threshold:
        return "researchable", "bounded_evidence_retrieval", confidence
    if bounded <= low or grounded <= low:
        return "not_researchable", "not_bounded_for_retrieval", confidence
    return "uncertain", "unresolved_researchability", confidence


def classify_decomposability(
    noul: Mapping[str, float], *, threshold: float
) -> tuple[Decomposability, str, float]:
    """Whether a robust answer is several separately researchable subconclusions.

    The components may concern the same subject. Evidence-object count, opposite
    outcomes of one component, and question length do not create a split.
    Reuse is logged and does not decide on its own.
    """
    low = 1 - threshold
    distinct = noul["robust_answer_requires_multiple_distinct_subconclusions"]
    separate = noul["subconclusions_can_be_researched_separately"]
    if distinct >= threshold and separate >= threshold:
        return (
            "decomposable",
            "multiple_distinct_researchable_subconclusions",
            min(distinct, separate),
        )
    if distinct <= low:
        return "not_decomposable", "single_conclusion_or_mapping", distinct
    if separate <= low:
        return "not_decomposable", "subconclusions_not_separately_researchable", separate
    return "uncertain", "unresolved_decomposability", min(distinct, separate)


def classify_decomposition(noul: Mapping[str, float], *, threshold: float) -> tuple[bool, str]:
    """Accept a set of individually valid children when the set itself progresses.

    The caller has already kept at least two children. Those children are
    distinct parts of one knowledge need. They do not have to be independent
    of each other, and candidate validation has already accepted each
    substantive subset, so ``independent`` and ``narrower`` do not veto.

    Reject when the children lack semantic progress, would not help answer
    the parent, or are mainly paraphrases. That rejection is what sends the
    parent to best-effort retrieval.
    """
    low = 1 - threshold
    if noul["paraphrase_risk"] > low:
        return False, "insufficient_semantic_progress"
    if any(noul[key] < threshold for key in _SET_PROGRESS_SIGNALS):
        return False, "insufficient_semantic_progress"
    return True, ""


def classify_child_redundancy(
    noul: Mapping[str, float],
    *,
    threshold: float,
    has_siblings: bool,
    has_ancestors: bool,
) -> tuple[bool, str]:
    """Accept a proper substantive subset. Reject the same whole question.

    Parent containment is not redundancy. ``same_knowledge_need_as_parent``
    often scores high for a child that is merely about the parent. A proper
    subset is ``candidate_adds_distinct_subconclusion`` or
    ``candidate_is_narrower_but_substantively_distinct`` at the threshold,
    and either one accepts the child. Parent containment rejects only when
    both subset signals are below the threshold. The same whole question as
    a sibling or ancestor still rejects. Signals for an empty sibling or
    ancestor list are ignored.
    """
    if has_siblings and noul["same_knowledge_need_as_sibling"] >= threshold:
        return False, "redundant_with_sibling"
    if has_ancestors and noul["same_knowledge_need_as_ancestor"] >= threshold:
        return False, "redundant_with_ancestor"
    distinct = noul["candidate_adds_distinct_subconclusion"]
    narrower = noul["candidate_is_narrower_but_substantively_distinct"]
    if distinct >= threshold or narrower >= threshold:
        return True, ""
    if noul["same_knowledge_need_as_parent"] >= threshold:
        return False, "redundant_with_parent"
    return False, "not_distinct_knowledge_need"


logger = logging.getLogger(__name__)


class JevQuestionTreeController:
    def __init__(self, client: JevSystemOne | None = None) -> None:
        self.client = client or HttpJevSystemOne()

    async def assess_structure(self, *, question: str) -> StructureDecision:
        result = await self._ask(
            {"question": question},
            STRUCTURE_QUESTIONS,
            evaluator_id=EVALUATOR_QUESTION_STRUCTURE,
            model_config=threshold_config(
                atomicity_threshold=settings.research_question_atomicity_threshold
            ),
        )
        noul = _nouls(result.answers, STRUCTURE_QUESTIONS)
        threshold = settings.research_question_atomicity_threshold
        researchability, research_reason, research_confidence = classify_researchability(
            noul, threshold=threshold
        )
        decomposability, decompose_reason, decompose_confidence = classify_decomposability(
            noul, threshold=threshold
        )
        if researchability == "uncertain" and decomposability == "uncertain":
            logger.warning(
                "jev question structure unresolved researchability=%s "
                "decomposability=%s question=%s",
                research_reason,
                decompose_reason,
                question[:240],
            )
        return StructureDecision(
            researchability=researchability,
            decomposability=decomposability,
            researchability_reason=research_reason,
            decomposability_reason=decompose_reason,
            researchability_confidence=research_confidence,
            decomposability_confidence=decompose_confidence,
            noul=noul,
            model_provider="jev",
            model=result.model,
            duration_ms=result.latency_ms,
            threshold=threshold,
        )

    async def validate_decomposition(
        self, *, question: str, children: Sequence[str]
    ) -> DecompositionDecision:
        result = await self._ask(
            {
                "question": question,
                "child_count": len(children),
                "child_questions": list(children),
            },
            DECOMPOSITION_VALIDATION_QUESTIONS,
            evaluator_id=EVALUATOR_DECOMPOSITION_VALIDATION,
            model_config=threshold_config(
                decomposition_threshold=settings.research_question_decomposition_threshold
            ),
        )
        noul = _nouls(result.answers, DECOMPOSITION_VALIDATION_QUESTIONS)
        threshold = settings.research_question_decomposition_threshold
        accepted, reason = classify_decomposition(noul, threshold=threshold)
        return DecompositionDecision(
            accepted=accepted,
            noul=noul,
            rejection_reason=reason,
            model_provider="jev",
            model=result.model,
            duration_ms=result.latency_ms,
            threshold=threshold,
        )

    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision:
        result = await self._ask(
            {
                "parent_question": parent,
                "candidate_question": candidate,
                "sibling_questions": list(siblings),
                "ancestor_questions": list(ancestors),
            },
            CHILD_REDUNDANCY_QUESTIONS,
            evaluator_id=EVALUATOR_CHILD_REDUNDANCY,
            model_config=threshold_config(
                decomposition_threshold=settings.research_question_decomposition_threshold
            ),
        )
        noul = _nouls(result.answers, CHILD_REDUNDANCY_QUESTIONS)
        threshold = settings.research_question_decomposition_threshold
        accepted, reason = classify_child_redundancy(
            noul,
            threshold=threshold,
            has_siblings=bool(siblings),
            has_ancestors=bool(ancestors),
        )
        return ChildRedundancyDecision(
            accepted=accepted,
            noul=noul,
            rejection_reason=reason,
            model_provider="jev",
            model=result.model,
            duration_ms=result.latency_ms,
            threshold=threshold,
        )

    async def assess_synthesis_readiness(
        self,
        *,
        question: str,
        child_answers: Sequence[AnswerInput],
    ) -> ReadinessDecision:
        result = await self._ask(
            _state(question, child_answers),
            READINESS_QUESTIONS,
            evaluator_id=EVALUATOR_SYNTHESIS_READINESS,
            model_config=threshold_config(
                readiness_threshold=settings.research_question_readiness_threshold
            ),
        )
        noul = _nouls(result.answers, READINESS_QUESTIONS)
        threshold = settings.research_question_readiness_threshold
        return ReadinessDecision(
            sufficient=noul["sufficient_to_answer_parent"] >= threshold,
            material_gap=noul["material_gap_remains"] >= threshold,
            additional_research_likely_to_change_answer=(
                noul["additional_research_likely_to_change_answer"] >= threshold
            ),
            noul=noul,
            model_provider="jev",
            model=result.model,
            duration_ms=result.latency_ms,
        )

    async def assess_completeness(
        self,
        *,
        question: str,
        answer: str,
        child_answers: Sequence[AnswerInput],
    ) -> CompletenessDecision:
        state = _state(question, child_answers)
        state["answer"] = answer
        result = await self._ask(
            state,
            READINESS_QUESTIONS,
            evaluator_id=EVALUATOR_QUESTION_COMPLETENESS,
            model_config=threshold_config(
                completeness_threshold=settings.research_question_completeness_threshold
            ),
        )
        noul = _nouls(result.answers, READINESS_QUESTIONS)
        threshold = settings.research_question_completeness_threshold
        gap = noul["material_gap_remains"] >= threshold
        change = noul["additional_research_likely_to_change_answer"] >= threshold
        sufficient = noul["sufficient_to_answer_parent"] >= threshold
        status = "answered" if sufficient and not gap else "answered_with_gaps"
        if not sufficient:
            status = "insufficient"
        return CompletenessDecision(
            status=status,
            material_gap=gap,
            additional_research_likely_to_change_answer=change,
            noul=noul,
            model_provider="jev",
            model=result.model,
            duration_ms=result.latency_ms,
        )

    async def _ask(
        self,
        state: dict[str, object],
        questions: dict[str, object],
        *,
        evaluator_id: str,
        model_config: dict[str, str],
    ):
        if not settings.research_jev_enabled or not settings.typesafe_api_key.strip():
            raise ValueError("Jev is required for recursive question research")
        return await evaluate_system_one(
            self.client,
            evaluator_id=evaluator_id,
            evaluator_version=EVALUATOR_VERSION_V1,
            state=state,
            questions=questions,
            model=research_jev_model(),
            timeout_seconds=settings.research_jev_timeout_seconds,
            required_signals=tuple(questions),
            policy_version=EVALUATION_POLICY_V1,
            model_config=model_config,
        )


def _state(question: str, answers: Sequence[AnswerInput]) -> dict[str, object]:
    return {
        "question": question,
        "child_answers": [
            {
                "question": item.question,
                "answer": item.answer,
                "status": item.status,
            }
            for item in answers
        ],
    }


def _nouls(answers: dict[str, object], questions: dict[str, object]) -> dict[str, float]:
    return {key: parse_noul(answers, key) for key in questions}
