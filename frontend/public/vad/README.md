# Silero VAD-model

`silero_vad.onnx` är Silero VAD v5 (MIT-licens) från
[snakers4/silero-vad](https://github.com/snakers4/silero-vad),
konverterad till ONNX av projektet.

- Fönster: 512 samples @ 16 kHz, context 64 samples, state 2×128.
- Körs i webbläsaren via `onnxruntime-web` (WASM, en tråd); se
  `frontend/src/products/sme/sileroModel.ts`.
- Uppdatera inte filen utan att köra frontend-testerna för VAD och verifiera
  att input-/outputnamnen (`input`, `state`, `sr` → `output`, `stateN`)
  fortfarande stämmer.
