"""The trace keeps the evidence chain behind a scripted verdict."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.benchmark import run_benchmark
from app.services.research.sufficiency_experiment.golden import (
    CONTRADICTION_SIGNAL,
    tail_counterevidence,
)
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev


async def test_trace_records_the_signal_passage_and_gate() -> None:
    report = await run_benchmark(
        (tail_counterevidence(),),
        client=ScriptedSufficiencyJev(),
        measurement="scripted",
        include_trace=True,
    )
    case = report.cases[0]
    assert case.trace is not None
    trace = case.trace
    assert trace["case_id"] == "tail_counterevidence"
    signal_rows = trace["signal_passages"]
    assert len(signal_rows) == 1
    assert signal_rows[0]["signal_present"] is True
    assert CONTRADICTION_SIGNAL in signal_rows[0]["text"]
    assert trace["contradiction_passages"] == [signal_rows[0]["passage_id"]]
    assert trace["quality"]["allows_sufficient"] is False
    assert "unresolved_conflicts" in trace["quality"]["reasons"]
    assert trace["verdict"]["llm_calls"] == 0
    assert trace["verdict"]["result"] == "insufficient"
    assert trace["verdict"]["status"] == "uncertain"
    assert trace["evaluations"]
    assert all("error" in row for row in trace["evaluations"])
    route = trace["route"]
    assert route is not None
    assert route["jev_outcome"] == "insufficient"
    assert route["jev_answers"]["contradiction"] == 0.95
    assert trace["route_state"]["unresolved_conflicts"]


async def test_trace_is_opt_in() -> None:
    report = await run_benchmark(
        (tail_counterevidence(),),
        client=ScriptedSufficiencyJev(),
        measurement="scripted",
    )
    assert report.cases[0].trace is None
