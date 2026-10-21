# Live Speech Fas 1 — measurements and acoustic status

Design goals from `docs/specs/live-speech-full-duplex.md` §7:

| Event | Goal |
|---|---:|
| Local VAD reaction | < 50 ms |
| Local playback stop | < 100 ms p95 |
| Clear barge-in | < 200 ms p95 |
| First natural response | < 500 ms when applicable |
| First content-bearing audio | < 1000 ms |

## What this PR can report

Automated tests measure **mechanism latency**, not a representative Swedish
call over a real network with a microphone and loudspeaker.

| Phase | Lab result | Notes |
|---|---|---|
| Rule classify (`stopp` / `mm` / `precis`) | p50 0.002 ms, p95 0.002 ms, p99 0.003 ms | In-process, 400×7 Swedish utterances |
| Local `cancel()` stop | synchronous (queue `stop()`) | Meets < 100 ms by construction once the partial is on the client |
| Uncertain confirm beat | 300 ms cap (`LIVE_SPEECH_BACKCHANNEL_CONFIRM_MS`) | Timeout no longer barges |
| TTS timeout | 8 s default, fail loud, one start/end | No second spoken reply |
| Speculation | default **off**; prefix reuse + parallel read-only | Hit/waste/incorrect counters on `session.metrics.speculation` |

Live `session.metrics` p50/p95/p99 must be collected from real sessions.
This cloud environment has no acoustic loopback, so those percentiles are
**not claimed**.

## Acoustic E2E checklist (manual, required before calling Fas 1 done)

1. Chrome + speakers: TTS must not be transcribed as a barge-in (AEC on).
2. Firefox or Safari + speakers: same echo check.
3. Headset: barge-in `stopp` / `nej` / `vänta` stops playback immediately;
   `mm` / `ja` / `precis` do not.
4. Record `session.metrics` from those calls and compare with the table above.

Until that checklist is run on hardware, Fas 1 is **not** marked complete.
