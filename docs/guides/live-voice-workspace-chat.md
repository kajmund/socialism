# Live Speech developer guide

## Setup

Configure these backend-only values:

```dotenv
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
LIVE_SPEECH_STT_MODEL=gpt-live-transcribe
LIVE_SPEECH_NOISE_REDUCTION=near_field
LIVE_SPEECH_TTS_MODEL=eleven_v4_turbo
LIVE_SPEECH_TTS_OUTPUT_FORMAT=pcm_24000
# Optional Silero VAD band (defaults 0.5 / 0.35, exit must stay below start):
LIVE_SPEECH_VAD_SILERO_THRESHOLD=0.5
LIVE_SPEECH_VAD_SILERO_EXIT_THRESHOLD=0.35
```

Apply Alembic through revision `162_live_speech_interrupted`. Install
dependencies with `uv sync` and `pnpm install`.

## Runtime

The browser connects to `/ws/live-speech` with the existing access token.
`useLiveSpeechConversation` captures 30 ms microphone frames. Silero VAD
decides speech, with a minimum speech duration and an urgent gate, and the
browser sends only active PCM16 audio. The Silero probability is smoothed and
gated with hysteresis (`LIVE_SPEECH_VAD_SILERO_THRESHOLD` opens speech at 0.5,
`LIVE_SPEECH_VAD_SILERO_EXIT_THRESHOLD` closes it at 0.35); both are sent per
session in `session.ready`. The Silero ONNX session loads once per page in a dedicated Web Worker (inference
never blocks the UI thread) and
preloads when the voice session starts; microphone frames are buffered up to
250 ms while it loads. The microphone is captured at 24 kHz: the browser's
filtered resampler does the 48k→24k step, Silero resamples 2:3 to 16 kHz, and
the sent PCM is already 24 kHz. A retryable empty transcript (VAD opened on
noise)
returns to listening without an error toast. Browser noise suppression is off;
OpenAI near-field noise reduction is the filter on that audio. Opening a
document sends `stt.focus` with that document's source id. The server loads
its text units and updates the transcription keywords with `session.update`.
Speech while the assistant talks is classified as
backchannel or barge-in. An urgent partial (`stopp`, `nej`, `vänta`, `stop`,
`wait`, `no`) stops playback locally and sends `turn.cancel` immediately,
without waiting for the server classifier. The opening line can be silenced the
same way. The session opens with a Fast line from the latest
interview messages so the expert speaks first. A long user turn can get a
Fast listener cue. If the expert has not spoken within 50 milliseconds of the
user's answer, a Fast waiting line is spoken. Tool progress is spoken as soon
as a tool runs. Neither line is persisted. The backend
transcribes with OpenAI Realtime and calls the same `execute_expert_turn`
used by `/ws/sme`. A typed message during speech cancels the turn and keeps
the voice session. A config-gated speculative reader prefetches read-only
`find_documents`/`search_knowledge` results on stable partials and reuses them
when the final question matches (`LIVE_SPEECH_SPECULATION_ENABLED`, default
off).
Model traces from that turn are forwarded on `/ws/live-speech` so
**Modellens arbete** updates during Socialism Voice without depending on
`/ws/sme`.

Experts select `socialism` as `live_voice_provider` to use this workspace-only
path. The saved `live_voice` is the ElevenLabs TTS voice ID; the configured
`ELEVENLABS_VOICE_ID` remains the default. Gemini and ElevenLabs continue
through their existing standalone provider sessions.

Do not add model routing to voice code. `expert_reasoning_turn` and
`llm/selection.py` own Jev and the Snabb/Balanserad/Djup profiles.

The token callback only emits/queues text. A voice turn streams the reply as
the tool episode generates it (acknowledgment first, then the episode tokens),
so first content audio does not wait for the whole tool episode. ElevenLabs TTS
runs in its own task
using the official `AsyncElevenLabs` stream. Never open or retain a database
transaction around OpenAI, LLM, ElevenLabs, playback waits or retries.

When `LIVE_SPEECH_TTS_MODEL=eleven_v4_turbo`, the active database prompt
`chat.expert.live_speech_delivery` asks the model for supported expression
tags. Raw tagged deltas go only to TTS. The WebSocket text stream, canonical
assistant message, memory and interrupted-turn persistence remove those tags;
citations such as `[R1]` remain unchanged.

## Protocol notes

- JSON controls and binary audio share one socket.
- Input and output are PCM16 mono at 24 kHz.
- `audio.output.start` and `audio.output.end` carry `response_id` and
  `generation_id`. A new generation starts for each reply or aside; barge-in
  also advances the generation fence.
- Downlink PCM frames are prefixed with a big-endian `uint32` generation id
  (`app/services/live_speech_pcm.py`). The client drops queued, in-flight and
  late websocket frames whose generation is blocked or not the active one.
- OpenAI transcription has `turn_detection: null` and `noise_reduction: near_field`; browser VAD sends commit.
- `stt.focus` carries source ids. The server turns the open document's text units into keywords.
- Binary output belongs to the most recent `audio.output.start`.
- `session.state` carries `conversation_state` (IDLE/USER_SPEAKING/USER_PAUSED/
  AI_THINKING/AI_SPEAKING/OVERLAPPING/AI_INTERRUPTED), owned by the
  Conversation Controller (`app/services/conversation_controller.py`).
- The client sends `client.latency` (`phase`, `milliseconds`) for phases it
  owns: `browser.vad_reaction`, `browser.stop_playback`,
  `browser.first_audible_audio`, and `browser.aec_applied`.
- On close the server emits `session.metrics` with p50/p95/p99 per phase and
  speculation counters (`cache_hits`, `wasted`, `incorrect`,
  `rejected_mismatch`, `latency_gain_ms`).
- Invalid sequences fail visibly. V1 does not reconnect in the middle of a turn.
- Starting a second session for the same user/workspace revokes the first.

## Verification

```bash
cd backend
uv run pytest tests/test_live_speech.py tests/test_live_speech_conversation.py
uv run ruff check app tests

cd ../frontend
pnpm lint
pnpm test
pnpm build
```

The default tests mock provider boundaries. Before activation, perform a live
browser check for microphone permission, Swedish partial/final transcript,
first playable audio, mute, explicit cancel, barge-in, typed text during
speech, socketdrop and history reload. Record p50/p95 latency with network
conditions and sample count.

## Latency measurement

`session.metrics` on socket close reports p50/p95/p99 for each named phase, so
a representative run can be summarized without code changes. Phases are
prefixed by owner:

- `browser.vad_reaction` — first captured frame → VAD opened
- `browser.stop_playback` — urgent partial → local queue cleared
- `browser.first_audible_audio` — `audio.output.start` → first PCM scheduled
- `browser.aec_applied` — 1 if `getSettings().echoCancellation` is true
- `server.first_partial` / `server.barge_classified` / `server.barge_in`
- `server.first_llm_delta` / `server.turn_complete` / `server.turn_cancelled`
- `provider.final_transcript` / `provider.first_tts_audio`

Speculative reuse is gated by `LIVE_SPEECH_SPECULATION_ENABLED` (default off).
Prefetch is read-only, parallel, TTL-bounded, and reused only when the final
question extends the partial under the same tenant/permission fingerprint.

To record p50/p95/p99: run several representative Swedish sessions, collect
the `session.metrics` payloads (and backend `live_speech.latency` log lines),
then aggregate each phase with the same percentiles the server uses
(`app/services/latency_stats.py`).
