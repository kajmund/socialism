# Live Speech Fas 1 — gap matrix after issue #400

Inventory of `main` after PR #395, then the P0 work in this change.
Status: **finns / delvis / saknas / verifierat**.

| P0 | Före #400 | Efter denna PR | Evidens |
|---|---|---|---|
| Eventdriven Conversation Controller, invariants, stale-turn | Delvis (tunn 7-state setter) | Finns | `conversation_controller.py`, `tests/test_conversation_controller.py` |
| Out-of-order / duplicate partial / late final / cancel-race / fail-closed reset | Saknas | Finns | controller reject reasons + `ProviderItemBinder` |
| Floor vs VAD vs model-work tracks | Saknas | Finns | `ConversationSnapshot` |
| Intelligent barge-in inkl. precis / stopp / nej | Delvis (`precis` saknades) | Finns | `live_speech_backchannel.py`, golden tests |
| Uncertain confirms without false barge | Delvis (timeout → stopp) | Finns | `confirm_barge` only stops on interrupt classes |
| Actual AEC, not just a constraint flag | Delvis | Delvis | `appliedEchoCancellation`; fail-closed if applied=false. Physical speaker/headset E2E **saknas i denna miljö** |
| TTS generation on every PCM frame + late-frame drop | Delvis (start/end only) | Finns | `live_speech_pcm.py`, client `splitGenerationFrame` |
| Streaming TTS during tool episodes | Finns (PR #395) | Verifierat oförändrat | `stream_expert_episode` |
| TTS timeout without double spoken reply | Saknas | Finns | coordinator `asyncio.timeout` |
| Speculative prefix reuse, scope, TTL, parallel | Delvis (exact + sequential, default off) | Delvis | Parallel prefetch + TTL + fresh permission hash. Result reuse is **exact query only** (search is not monotonic). Default still off |
| p50/p95/p99 by browser/server/provider | Delvis (unprefixed phases) | Finns i kod | `LatencyStats` + `session.metrics`; **live acoustic values not collected here** |
| ≥30 Swedish golden scenarios | Saknas | Finns | `tests/test_live_speech_golden.py` |
| Real mic/speaker AEC on two browsers + headset | Saknas | Saknas | Cannot be signed off from this VM. Simulated echo + `getSettings` only |

## Fas 2 (do not build yet)

- Continuous overlapping dialogue (talk-over without stopping).
- Mid-sentence replanning of unspoken TTS segments inside one LLM stream.
- Floor arbitration with group raise-hand vs 1:1.
- Never rewrite already-spoken content; never read tool results from stale assumptions.

Current `amend` remains the Fas 2 seed: it stops playback and injects a correction into the same turn between tool rounds.
