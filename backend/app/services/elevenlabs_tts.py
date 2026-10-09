"""Thin cancellable adapter around ElevenLabs' official async TTS stream."""

from collections.abc import AsyncIterator

from elevenlabs.client import AsyncElevenLabs


class ElevenLabsTts:
    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str,
    ) -> None:
        self._client = AsyncElevenLabs(api_key=api_key)
        self._voice_id = voice_id
        self._model_id = model_id
        self._output_format = output_format

    async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
        chunks = self._client.text_to_speech.stream(
            self._voice_id,
            text=text,
            model_id=self._model_id,
            output_format=self._output_format,
            language_code=language,
        )
        async for chunk in chunks:
            if chunk:
                yield chunk

