# Live Speech developer guide

## Setup

Configure these backend-only values:

```dotenv
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
LIVE_SPEECH_STT_MODEL=gpt-live-transcribe
LIVE_SPEECH_TTS_MODEL=eleven_v4_turbo
LIVE_SPEECH_TTS_OUTPUT_FORMAT=pcm_24000
```

Apply Alembic through revision `162_live_speech_interrupted`. Install
dependencies with `uv sync` and `pnpm install`.

## Runtime

The browser connects to `/ws/live-speech` with the existing access token.
`useLiveSpeechConversation` captures 30 ms microphone frames, performs local
energy VAD with a minimum speech duration and an urgent gate, and sends only
active PCM16 audio. Speech while the assistant talks is classified as
backchannel or barge-in. The session opens with a Fast line from the latest
interview messages so the expert speaks first. A long user turn can get a
Fast listener cue. Slow tools can get Fast progress talk that is not
persisted. The backend
transcribes with OpenAI Realtime and calls the same `execute_expert_turn`
used by `/ws/sme`. A typed message during speech cancels the turn and keeps
the voice session.
Model traces from that turn are forwarded on `/ws/live-speech` so
**Modellens arbete** updates during Socialism Voice without depending on
`/ws/sme`.

Experts select `socialism` as `live_voice_provider` to use this workspace-only
path. The saved `live_voice` is the ElevenLabs TTS voice ID; the configured
`ELEVENLABS_VOICE_ID` remains the default. Gemini and ElevenLabs continue
through their existing standalone provider sessions.

Do not add model routing to voice code. `expert_reasoning_turn` and
`llm/selection.py` own Jev and the Snabb/Balanserad/Djup profiles.

The token callback only emits/queues text. ElevenLabs TTS runs in its own task
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
- OpenAI transcription has `turn_detection: null`; browser VAD sends commit.
- Binary output belongs to the most recent `audio.output.start`.
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
