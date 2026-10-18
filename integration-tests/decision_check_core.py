"""Shared runner for live decision-model checks against System One endpoints.

The golden set, HTTP client, judging and reporting live here; entry scripts
supply endpoint configuration (api_key, base_url, model) and formatting. One
HTTP call per case; the runner measures per-call latency and judges each
answer against the expected value. Clef and Jev share the /v1/systemone
protocol, so the same runner drives both.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

QuestionType = Literal["choice", "noul", "score"]


class AuthError(Exception):
    """The endpoint rejected the API key; abort the run."""


@dataclass(frozen=True)
class CaseSpec:
    id: str
    type: QuestionType
    state: str
    instructions: str
    expected: object
    criteria: dict[str, str] | list[str] | None = None


@dataclass(frozen=True)
class RunConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float


@dataclass
class CaseOutcome:
    case: CaseSpec
    ok: bool
    latency_ms: float
    input_chars: int
    actual: Any | None = None
    correct: bool | None = None
    error: str | None = None
    probabilities: dict[str, float] | None = None
    usage: dict[str, Any] | None = None
    resolved_model: str | None = None


# Golden set in the product domain. Expected answers are near-objective facts
# about the text so quality is measured, not political taste.
CASES: tuple[CaseSpec, ...] = (
    # choice — route a message to the policy area it is mainly about.
    CaseSpec(
        id="choice_skola",
        type="choice",
        state="Vi investerar 20 miljarder i nya klassrum, fler lärare och utbyggd skolmat.",
        instructions="Vilket politikområde handlar texten främst om?",
        criteria={
            "ekonomi": "Skatter, budget, jobb och företagande",
            "skola": "Utbildning, skolpolitik och elever",
            "sjukvard": "Vård, vårdköer och sjukvårdspersonal",
            "migration": "Invandring, asyl och gränskontroller",
            "miljo": "Klimat, utsläpp och energipolitik",
        },
        expected="skola",
    ),
    CaseSpec(
        id="choice_ekonomi",
        type="choice",
        state="Skatten måste sänkas för småföretagare så att fler jobb kan skapas.",
        instructions="Vilket politikområde handlar texten främst om?",
        criteria={
            "ekonomi": "Skatter, budget, jobb och företagande",
            "skola": "Utbildning, skolpolitik och elever",
            "sjukvard": "Vård, vårdköer och sjukvårdspersonal",
            "migration": "Invandring, asyl och gränskontroller",
            "miljo": "Klimat, utsläpp och energipolitik",
        },
        expected="ekonomi",
    ),
    CaseSpec(
        id="choice_migration",
        type="choice",
        state="Sverige ska ta emot färre asylsökande och skärpa gränskontrollerna.",
        instructions="Vilket politikområde handlar texten främst om?",
        criteria={
            "ekonomi": "Skatter, budget, jobb och företagande",
            "skola": "Utbildning, skolpolitik och elever",
            "sjukvard": "Vård, vårdköer och sjukvårdspersonal",
            "migration": "Invandring, asyl och gränskontroller",
            "miljo": "Klimat, utsläpp och energipolitik",
        },
        expected="migration",
    ),
    CaseSpec(
        id="choice_miljo",
        type="choice",
        state="Utsläppen måste minska med 70 procent till 2030 – vi satsar på vindkraft och tåg.",
        instructions="Vilket politikområde handlar texten främst om?",
        criteria={
            "ekonomi": "Skatter, budget, jobb och företagande",
            "skola": "Utbildning, skolpolitik och elever",
            "sjukvard": "Vård, vårdköer och sjukvårdspersonal",
            "migration": "Invandring, asyl och gränskontroller",
            "miljo": "Klimat, utsläpp och energipolitik",
        },
        expected="miljo",
    ),
    CaseSpec(
        id="choice_sjukvard",
        type="choice",
        state="Vi behöver kortare vårdköer och fler sjuksköterskor i hela landet.",
        instructions="Vilket politikområde handlar texten främst om?",
        criteria={
            "ekonomi": "Skatter, budget, jobb och företagande",
            "skola": "Utbildning, skolpolitik och elever",
            "sjukvard": "Vård, vårdköer och sjukvårdspersonal",
            "migration": "Invandring, asyl och gränskontroller",
            "miljo": "Klimat, utsläpp och energipolitik",
        },
        expected="sjukvard",
    ),
    # noul — yes/no properties of the text.
    CaseSpec(
        id="noul_skattesankning",
        type="noul",
        state="Regeringen sänker skatten för låg- och medelinkomsttagare med 12 "
        "miljarder kronor nästa år.",
        instructions="Innehåller texten ett konkret skattesänkningsförslag?",
        expected=True,
    ),
    CaseSpec(
        id="noul_ej_sjukvard",
        type="noul",
        state="Vi måste rusta upp skolan. Fler lärare, mindre klasser och gratis "
        "skolmat åt alla elever.",
        instructions="Handlar texten om sjukvård?",
        expected=False,
    ),
    CaseSpec(
        id="noul_avgangsbesked",
        type="noul",
        state="Statsministern avgår med omedelbar verkan efter intern kritik.",
        instructions="Rapporterar texten ett politiskt avgångsbesked?",
        expected=True,
    ),
    CaseSpec(
        id="noul_ej_politikerkritik",
        type="noul",
        state="Kommunen planerar en ny cykelbana längs Strandvägen.",
        instructions="Innehåller texten kritik mot en namngiven politiker?",
        expected=False,
    ),
    CaseSpec(
        id="noul_krav_mot_regeringen",
        type="noul",
        state="Oppositionen kräver att regeringen tar ansvar för elpriserna i vinter.",
        instructions="Innehåller texten ett krav riktat mot regeringen?",
        expected=True,
    ),
    # score — how clearly the text takes a political stand, level 0 to 2.
    CaseSpec(
        id="score_neutral_regioner",
        type="score",
        state="Sverige är indelat i 21 regioner som ansvarar för hälso- och sjukvården.",
        instructions="Hur tydligt tar texten politisk ställning? 0 = neutralt "
        "konstaterande, 1 = visst ställningstagande, 2 = tydligt ställningstagande.",
        criteria=["Neutralt konstaterande", "Visst ställningstagande", "Tydligt ställningstagande"],
        expected=0,
    ),
    CaseSpec(
        id="score_neutral_skattesats",
        type="score",
        state="Kommunalskatten ligger i genomsnitt på drygt 32 procent, enligt SCB.",
        instructions="Hur tydligt tar texten politisk ställning? 0 = neutralt "
        "konstaterande, 1 = visst ställningstagande, 2 = tydligt ställningstagande.",
        criteria=["Neutralt konstaterande", "Visst ställningstagande", "Tydligt ställningstagande"],
        expected=0,
    ),
    CaseSpec(
        id="score_mild_skatt",
        type="score",
        state="Det kan finnas skäl att se över skattesystemet, men frågan kräver "
        "mer utredning.",
        instructions="Hur tydligt tar texten politisk ställning? 0 = neutralt "
        "konstaterande, 1 = visst ställningstagande, 2 = tydligt ställningstagande.",
        criteria=["Neutralt konstaterande", "Visst ställningstagande", "Tydligt ställningstagande"],
        expected=1,
    ),
    CaseSpec(
        id="score_mild_klimat",
        type="score",
        state="Vi borde prioritera klimatet högre, men samtidigt måste jobben värnas.",
        instructions="Hur tydligt tar texten politisk ställning? 0 = neutralt "
        "konstaterande, 1 = visst ställningstagande, 2 = tydligt ställningstagande.",
        criteria=["Neutralt konstaterande", "Visst ställningstagande", "Tydligt ställningstagande"],
        expected=1,
    ),
    CaseSpec(
        id="score_tydlig_skolpolitik",
        type="score",
        state="Regeringens skolpolitik är ett totalt misslyckande som sviker en "
        "hel generation elever.",
        instructions="Hur tydligt tar texten politisk ställning? 0 = neutralt "
        "konstaterande, 1 = visst ställningstagande, 2 = tydligt ställningstagande.",
        criteria=["Neutralt konstaterande", "Visst ställningstagande", "Tydligt ställningstagande"],
        expected=2,
    ),
)


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _questions_for(case: CaseSpec) -> dict[str, Any]:
    question: dict[str, Any] = {"type": case.type, "instructions": case.instructions}
    if case.criteria is not None:
        question["criteria"] = case.criteria
    return {"q": question}


def _judge(case: CaseSpec, answers: dict[str, Any]) -> tuple[bool, Any]:
    row = answers.get("q")
    if not isinstance(row, dict):
        raise ValueError(f"answer for {case.id} is missing or not an object")
    if case.type == "choice":
        choice = row.get("choice")
        if not isinstance(choice, str):
            raise ValueError(f"choice answer for {case.id} is missing")
        return choice == case.expected, choice
    if case.type == "noul":
        probability = row.get("noul")
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            raise ValueError(f"noul answer for {case.id} is missing")
        value = float(probability)
        return (value >= 0.5) == bool(case.expected), value
    level = row.get("score")
    if not isinstance(level, (int, float)) or isinstance(level, bool):
        raise ValueError(f"score answer for {case.id} is missing")
    value = float(level)
    return abs(value - int(case.expected)) <= 0.5, value


async def _ask_once(
    client: httpx.AsyncClient, config: RunConfig, case: CaseSpec
) -> CaseOutcome:
    url = f"{config.base_url}/v1/systemone"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    body = {"model": config.model, "state": case.state, "questions": _questions_for(case)}
    started = time.perf_counter()
    try:
        response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return _failed(case, started, "timeout")
    except httpx.HTTPError as exc:
        return _failed(case, started, f"transport: {exc.__class__.__name__}")
    return _parse_response(case, response, started)


def _parse_response(
    case: CaseSpec, response: httpx.Response, started: float
) -> CaseOutcome:
    latency_ms = (time.perf_counter() - started) * 1000
    if response.status_code in {401, 403}:
        raise AuthError(f"rejected the API key (HTTP {response.status_code})")
    if response.status_code >= 400:
        return _failed(case, started, f"http_{response.status_code}", latency_ms=latency_ms)
    try:
        payload = response.json()
    except ValueError:
        return _failed(case, started, "not_json", latency_ms=latency_ms)
    if not isinstance(payload, dict):
        return _failed(case, started, "not_object", latency_ms=latency_ms)
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return _failed(case, started, "missing_answers", latency_ms=latency_ms)
    try:
        correct, actual = _judge(case, answers)
    except ValueError as exc:
        return _failed(case, started, f"malformed: {exc}", latency_ms=latency_ms)
    row = answers["q"]
    probabilities = None
    if isinstance(row, dict):
        raw_probabilities = row.get("probabilities")
        if isinstance(raw_probabilities, dict):
            probabilities = {
                str(key): float(value)
                for key, value in raw_probabilities.items()
                if isinstance(value, (int, float))
            }
    usage = payload.get("usage")
    resolved_model = payload.get("model")
    return CaseOutcome(
        case=case,
        ok=True,
        latency_ms=latency_ms,
        input_chars=len(case.state),
        actual=actual,
        correct=correct,
        probabilities=probabilities,
        usage=usage if isinstance(usage, dict) else None,
        resolved_model=str(resolved_model) if resolved_model else None,
    )


def _failed(
    case: CaseSpec, started: float, error: str, *, latency_ms: float | None = None
) -> CaseOutcome:
    measured = latency_ms if latency_ms is not None else (time.perf_counter() - started) * 1000
    return CaseOutcome(
        case=case,
        ok=False,
        latency_ms=measured,
        input_chars=len(case.state),
        error=error,
    )


def _percentile(ordered: list[float], fraction: float) -> float:
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _latency_stats(latencies: list[float]) -> dict[str, float]:
    if not latencies:
        return {}
    ordered = sorted(latencies)
    return {
        "min_ms": round(ordered[0], 1),
        "median_ms": round(_percentile(ordered, 0.5), 1),
        "p95_ms": round(_percentile(ordered, 0.95), 1),
        "max_ms": round(ordered[-1], 1),
        "mean_ms": round(sum(ordered) / len(ordered), 1),
    }


def _accuracy_by_type(outcomes: list[CaseOutcome]) -> dict[str, float]:
    by_type: dict[str, list[bool]] = {}
    for outcome in outcomes:
        if outcome.correct is not None:
            by_type.setdefault(outcome.case.type, []).append(outcome.correct)
    return {
        question_type: sum(correct) / len(correct)
        for question_type, correct in by_type.items()
        if correct
    }


def _case_record(outcome: CaseOutcome) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": outcome.case.id,
        "type": outcome.case.type,
        "state": outcome.case.state,
        "expected": outcome.case.expected,
        "actual": outcome.actual,
        "correct": outcome.correct,
        "ok": outcome.ok,
        "latency_ms": round(outcome.latency_ms, 1),
        "input_chars": outcome.input_chars,
    }
    if outcome.probabilities is not None:
        record["probabilities"] = outcome.probabilities
    if outcome.usage is not None:
        record["usage"] = outcome.usage
    if outcome.resolved_model is not None:
        record["resolved_model"] = outcome.resolved_model
    if outcome.error is not None:
        record["error"] = outcome.error
    return record


async def run_report(config: RunConfig, *, stage: str) -> dict[str, Any]:
    started = time.perf_counter()
    outcomes: list[CaseOutcome] = []
    timeout = httpx.Timeout(config.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for case in CASES:
            outcome = await _ask_once(client, config, case)
            outcomes.append(outcome)
            if outcome.ok:
                mark = "ok" if outcome.correct else "wrong"
            else:
                mark = outcome.error or "failed"
            print(
                json.dumps(
                    {
                        "stage": stage,
                        "case": case.id,
                        "type": case.type,
                        "result": mark,
                        "latency_ms": round(outcome.latency_ms, 1),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    total_wall_seconds = time.perf_counter() - started
    completed = [outcome for outcome in outcomes if outcome.ok]
    answered = [outcome for outcome in completed if outcome.correct is not None]
    correct_count = sum(1 for outcome in answered if outcome.correct)
    accuracy = correct_count / len(answered) if answered else 0.0
    summary = {
        "cases_total": len(CASES),
        "cases_completed": len(completed),
        "cases_failed": len(outcomes) - len(completed),
        "cases_correct": correct_count,
        "accuracy_overall": round(accuracy, 3),
        "accuracy_by_type": _accuracy_by_type(completed),
        "latency": _latency_stats([outcome.latency_ms for outcome in completed]),
        "total_wall_seconds": round(total_wall_seconds, 2),
    }
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "model": config.model,
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
        },
        "summary": summary,
        "cases": [_case_record(outcome) for outcome in outcomes],
        "extra": {"note": "text-only golden set; image judgment is not exercised"},
    }
