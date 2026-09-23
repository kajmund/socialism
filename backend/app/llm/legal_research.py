"""Structured domain extraction from a retrieved lagen.nu document."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError, create_model, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.legal_research_result import (
    CaseLawAnalysis,
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
    PreparatoryAttribution,
    PreparatoryTextRole,
    PreparatoryWorkAnalysis,
    StatuteAnalysis,
)
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.failures import FailureCategory
from app.services.research.models import ResearchContext

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class LegalDomainExtractionError(Exception):
    """The model could not produce a verified interpretation of this document."""

    def __init__(
        self, message: str, *, category: FailureCategory = "domain_schema_invalid"
    ) -> None:
        super().__init__(message)
        self.category = category


class LegalInterpretation(BaseModel):
    relation: LegalQuestionRelation
    case_law: CaseLawAnalysis | None = None
    preparatory_work: PreparatoryWorkAnalysis | None = None
    statute: StatuteAnalysis | None = None

    @model_validator(mode="after")
    def one_analysis(self) -> LegalInterpretation:
        if (
            sum(item is not None for item in (self.case_law, self.preparatory_work, self.statute))
            != 1
        ):
            raise ValueError("exactly one analysis is required")
        if self.preparatory_work is not None:
            attribution = self.preparatory_work.attribution
            if attribution is None:
                raise ValueError("preparatory analysis requires source attribution")
            if self.relation.relation == "supports" and (
                attribution.text_role in {"unknown", "contents"}
                or attribution.requested_text_role not in {"any", attribution.text_role}
            ):
                restriction = (
                    f"Source text role '{attribution.text_role}' does not establish the requested "
                    f"role '{attribution.requested_text_role}'. The model's proposed direct support "
                    "was restricted to contextual evidence by the source attribution check."
                )
                self.relation = self.relation.model_copy(update={
                    "relation": "contextual", "confidence": "low", "explanation": restriction,
                    "unresolved_questions": [*self.relation.unresolved_questions,
                        f"Retrieve evidence establishing requested text role: {attribution.requested_text_role}"],
                })
                self.preparatory_work.limitations.append(restriction)
        return self


class PreparatorySourceRole(BaseModel):
    speaker: str
    text_role: PreparatoryTextRole
    role_span_ids: list[str] = Field(min_length=1, max_length=3)


class DecidingCourtPassage(BaseModel):
    explanation: str
    reasoning_start: str
    reasoning_end: str


class LegalInterpreter(Protocol):
    async def interpret(
        self,
        *,
        source: LegalSourceIdentity,
        question: str,
        raw_text: str,
        truncated: bool,
        context: ResearchContext,
    ) -> LegalResearchResult: ...


class LlmLegalInterpreter:
    def __init__(
        self,
        *,
        completer: Completer | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._completer = completer or complete_structured_retry
        self._session_factory = session_factory or SessionLocal

    async def _preparatory_source_role(
        self, *, prompts: dict[str, str], spans: dict[str, str], source: LegalSourceIdentity,
    ) -> PreparatoryAttribution:
        # Classify source context without the research question to avoid priming.
        visible: dict[str, str] = {}
        used = 0
        for key, paragraph in spans.items():
            if used + len(paragraph) > 16000:
                break
            visible[key] = paragraph
            used += len(paragraph)
        if not visible:
            raise LegalDomainExtractionError("No bounded source context available for attribution")
        message = render_prompt(
            prompts, "research.lagen_nu.domain.v3.preparatory_role",
            source_text="\n\n".join(f"[{key}]\n{text}" for key, text in visible.items()),
        )
        try:
            response = await invoke_structured_completer(
                self._completer, [{"role": "user", "content": message}], PreparatorySourceRole,
                prompt_key="research.lagen_nu.domain.v3.preparatory_role",
            )
            role = PreparatorySourceRole.model_validate(response)
            if any(key not in visible for key in role.role_span_ids):
                raise ValueError("attribution cites an unavailable source span")
            return PreparatoryAttribution(
                speaker=role.speaker, text_role=role.text_role, requested_text_role="unknown",
                role_citations=[LegalCitation(source_uri=source.canonical_uri, quote=visible[key], source_span_id=key) for key in role.role_span_ids],
            )
        except Exception as exc:
            raise LegalDomainExtractionError(f"Source attribution failed: {exc}") from exc

    async def interpret(
        self,
        *,
        source: LegalSourceIdentity,
        question: str,
        raw_text: str,
        truncated: bool,
        context: ResearchContext,
    ) -> LegalResearchResult:
        customer_id = context.scope.customer_id
        module = context.scope.module
        if customer_id is None or not module:
            raise ValueError("legal interpreter requires customer_id and module")
        async with self._session_factory() as session:
            prompts = await require_active_prompts(
                session, customer_id=customer_id, module=module, language="sv"
            )
        spans = {
            f"s{index}": paragraph
            for index, paragraph in enumerate(raw_text.split("\n\n"))
            if paragraph.strip()
        }
        marked_source = "\n\n".join(f"[{key}]\n{text}" for key, text in spans.items())
        holding_text = None
        if source.kind == "case_law":
            passage_schema = create_model(
                "DecidingCourtPassageSelection",
                __base__=DecidingCourtPassage,
                reasoning_start=(Literal[tuple(spans)], ...),
                reasoning_end=(Literal[tuple(spans)], ...),
            )
            try:
                selection = passage_schema.model_validate(
                    await invoke_structured_completer(
                        self._completer,
                        [
                            {
                                "role": "system",
                                "content": render_prompt(
                                    prompts, "research.lagen_nu.domain.v3.court_passage_v2"
                                ),
                            },
                            {"role": "user", "content": marked_source},
                        ],
                        passage_schema,
                        prompt_key="research.lagen_nu.domain.v3.system",
                    )
                )
            except Exception as exc:
                raise LegalDomainExtractionError(
                    f"deciding court source selection failed: {exc}"
                ) from exc
            keys = list(spans)
            if selection.reasoning_start not in spans or selection.reasoning_end not in spans:
                raise LegalDomainExtractionError(
                    "deciding court passage has unknown source span",
                    category="citation_grounding_failed",
                )
            start = keys.index(selection.reasoning_start)
            end = keys.index(selection.reasoning_end)
            if end < start:
                raise LegalDomainExtractionError("deciding court passage ends before it starts")
            holding_text = "\n\n".join(spans[key] for key in keys[start : end + 1])
            marked_source = render_prompt(
                prompts,
                "research.lagen_nu.domain.v3.court_analysis",
                court_text="\n\n".join(f"[{key}]\n{spans[key]}" for key in keys[start : end + 1]),
            )
        messages = [
            {
                "role": "system",
                "content": render_prompt(prompts, "research.lagen_nu.domain.v3.system"),
            },
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.domain.v3.user",
                    question=question,
                    source_kind=source.kind,
                    source_uri=source.canonical_uri,
                    source_text=("[truncated=true]\n" if truncated else "[truncated=false]\n")
                    + marked_source,
                ),
            },
        ]
        if source.kind == "preparatory_work":
            messages[0]["content"] += "\n\n" + render_prompt(
                prompts, "research.lagen_nu.domain.v3.preparatory_attribution"
            )
        source_attribution = None
        if source.kind == "preparatory_work":
            source_attribution = await self._preparatory_source_role(
                prompts=prompts, spans=spans, source=source,
            )
            messages[1]["content"] += "\n\nSource attribution (independently classified):\n" + source_attribution.model_dump_json(exclude={"requested_text_role"})
        analysis_type = {
            "case_law": CaseLawAnalysis,
            "preparatory_work": PreparatoryWorkAnalysis,
            "statute": StatuteAnalysis,
        }[source.kind]
        interpretation_schema = create_model(
            "LegalInterpretation",
            **{source.kind: (analysis_type, ...)},
            relation=(LegalQuestionRelation, ...),
        )
        for attempt in range(3):
            parsed = None
            try:
                response = await invoke_structured_completer(
                    self._completer,
                    messages,
                    interpretation_schema,
                    prompt_key="research.lagen_nu.domain.v3.system",
                )
                payload = response.model_dump() if isinstance(response, BaseModel) else response
                if source_attribution is not None and isinstance(payload, dict):
                    analysis_payload = payload.get("preparatory_work")
                    if isinstance(analysis_payload, dict):
                        proposed = analysis_payload.get("attribution") or {}
                        analysis_payload["attribution"] = {
                            **source_attribution.model_dump(),
                            "requested_text_role": proposed.get("requested_text_role", "unknown"),
                        }
                parsed = LegalInterpretation.model_validate(payload)
                analysis = parsed.case_law or parsed.preparatory_work or parsed.statute
                assert analysis is not None
                citations = list(analysis.citations)
                if parsed.preparatory_work and parsed.preparatory_work.attribution:
                    citations.extend(parsed.preparatory_work.attribution.role_citations)
                if parsed.case_law:
                    statements = list(parsed.case_law.other_statements)
                    if parsed.case_law.authoritative_holding:
                        statements.append(parsed.case_law.authoritative_holding)
                    citations.extend(
                        citation for statement in statements for citation in statement.citations
                    )
                for citation in citations:
                    if citation.source_span_id is not None:
                        if citation.source_span_id not in spans:
                            raise LegalDomainExtractionError(
                                f"unknown source span: {citation.source_span_id}",
                                category="citation_grounding_failed",
                            )
                        citation.quote = spans[citation.source_span_id]
                if holding_text is not None and any(
                    citation.quote not in holding_text for citation in citations
                ):
                    raise LegalDomainExtractionError(
                        "authoritative citation is outside deciding court passage",
                        category="citation_grounding_failed",
                    )
                return LegalResearchResult(
                    source=source,
                    relation=parsed.relation,
                    case_law=parsed.case_law,
                    preparatory_work=parsed.preparatory_work,
                    statute=parsed.statute,
                    raw_text=raw_text,
                    truncated=truncated,
                )
            except (ValidationError, LegalDomainExtractionError) as exc:
                if isinstance(exc, LegalDomainExtractionError):
                    if exc.category != "citation_grounding_failed":
                        raise
                    category = exc.category
                    detail = str(exc)
                else:
                    category = "domain_schema_invalid"
                    if any(
                        error.get("ctx", {}).get("error").__class__.__name__
                        == "CitationGroundingError"
                        for error in exc.errors()
                    ):
                        category = "citation_grounding_failed"
                    detail = "; ".join(f"{error['loc']}: {error['msg']}" for error in exc.errors())
                if attempt == 2:
                    raise LegalDomainExtractionError(detail, category=category) from exc
                if parsed is not None:
                    messages.append({"role": "assistant", "content": parsed.model_dump_json()})
                messages.append(
                    {
                        "role": "user",
                        "content": render_prompt(
                            prompts,
                            "research.lagen_nu.domain.v3.repair",
                            validation_errors=detail,
                        ),
                    }
                )
            except Exception as exc:
                raise LegalDomainExtractionError(f"{type(exc).__name__}: {exc}") from exc
        raise AssertionError("unreachable")
