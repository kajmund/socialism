# Live Speech provider verification

## 2026-10-08

Environment: local backend, configured project credentials, Swedish language,
PCM16 24 kHz.

### OpenAI Realtime transcription

Configured model: `gpt-live-transcribe`.

The first WebSocket attempt incorrectly supplied `gpt-live-transcribe` as the
Realtime handshake model and was rejected with
`invalid_request_error.invalid_model`. The corrected connection uses
`intent=transcription` in the WebSocket query and selects the model only in the
documented transcription `session.update`, with `turn_detection: null`.

Result: **transport accepted**. The provider returned `session.created` and
`session.updated` for the configured project and model. This verifies session
setup but not yet partial/final events from representative Swedish microphone
audio.

### ElevenLabs streaming TTS

Configured `eleven_v4_turbo` model, voice ID and `pcm_24000` output were tested through the
official Python SDK `AsyncElevenLabs.text_to_speech.stream` with the Swedish
text “Hej.”. The stream returned its first 1,024-byte PCM chunk.

Result: **transport accepted**. This is not yet the required browser listening
test for Swedish prosody, segment continuity and abrupt barge-in.
