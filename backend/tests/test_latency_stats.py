from app.services.latency_stats import LatencyStats, percentiles


def test_percentiles_empty_is_zeros():
    assert percentiles([]) == (0.0, 0.0, 0.0)


def test_percentiles_median_and_tails():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0]
    p50, p95, p99 = percentiles(samples)
    assert p50 == 3.0
    assert p95 == 4.8
    assert p99 == 4.96


def test_latency_stats_summarizes_each_phase():
    stats = LatencyStats()
    stats.add("first_tts_audio", 200.0)
    stats.add("first_tts_audio", 300.0)
    stats.add("first_tts_audio", 400.0)
    stats.add("barge_in", 100.0)

    summary = stats.summary()
    assert summary["first_tts_audio"]["count"] == 3
    assert summary["first_tts_audio"]["p50_ms"] == 300.0
    assert summary["barge_in"]["p50_ms"] == 100.0
