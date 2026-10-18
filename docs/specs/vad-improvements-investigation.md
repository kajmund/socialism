# VAD i live-röstchatten — undersökning och förbättringsförslag

Status: undersökning klar; P1 (preload + singleton + preroll-buffert), P2
(hysteres + utjämning + serverstyrd Silero-tröskel), P5 (tyst retryable
`empty_transcript`), P7 (config-/dokumentationsstädning), P3 (capture vid
24 kHz) och P4 (ONNX-inferens i Web Worker) är genomförda.
P6 (offline-eval) återstår.
Omfattning: klient-VAD (Silero ONNX i webbläsaren) för live speech i SME-chatten,
enkel expert och gruppröst. Serverns barge-in/backchannel-klassificering berörs
endast indirekt.

## 1. Dagens lösning

```text
Mikrofon (AudioContext, enhetsfrekvens, typiskt 48 kHz)
  → pcmCapture.worklet.ts (30 ms-ramar)
  → sileroGate.ts (linjär resampling till 16 kHz, 512-samplesfönster,
     Silero VAD v5 via onnxruntime-web, tröskel hårdkodad 0.5)
  → turnVad.ts (turssegmentering: preroll/hangover/min-taltid/urgent-grind)
  → PCM16 24 kHz till /ws/live-speech (audio.start / frames / audio.commit)
  → OpenAI gpt-live-transcribe (turn_detection=null, near_field)
```

Relevanta filer:

- `frontend/src/products/sme/speechVad.ts` — komponerar SileroGate + TurnVad
- `frontend/src/products/sme/sileroGate.ts` — fönstring, resampling, tröskel
- `frontend/src/products/sme/sileroModel.ts` — ONNX-session och Silero-tillstånd
- `frontend/src/products/sme/turnVad.ts` — turssegmentering (vältestad, 6 tester)
- `frontend/src/components/chat/pcmCapture.worklet.ts` — 30 ms-mikrofonramar
- `frontend/src/components/chat/liveVoiceAudio.ts` — `encodePcm16` (→ 24 kHz)
- `frontend/src/products/sme/useLiveSpeechConversation.ts` — enkel expert
- `frontend/src/products/sme/useSmeGroupVoice.ts` — gruppröst (delar speechVad)
- `backend/app/live_speech_settings.py` — `vad_client_config()` → `session.ready`
- `backend/app/api/live_speech.py` / `backend/app/api/sme_group_voice_ws.py`
- `frontend/public/vad/silero_vad.onnx` — modell, 2,3 MB (ospårad i git)

Standardparametrar (skickas från servern per session):

| Nyckel | Default | Används idag |
| --- | --- | --- |
| `preroll_ms` | 250 | ja (TurnVad) |
| `hangover_ms` | 600 | ja (TurnVad) |
| `min_speech_ms` | 120 | ja (TurnVad) |
| `urgent_ms` | 120 | ja (TurnVad) |
| `threshold` | 0.018 | **nej — död konfiguration** |

## 2. Fynd

### F1. Server-konfigens `threshold` är död — Silero-tröskeln är hårdkodad

`vad_client_config()` skickar `threshold` (`live_speech_vad_threshold`,
default 0.018, en rest från den gamla energibaserade VAD:en i
`liveSpeechVad.ts` som raderats ur arbetsytan). Klienten läser den aldrig:
`turnVadFromConfig()` i `frontend/src/products/sme/turnVad.ts:94-102` plockar
bara preroll/hangover/min_speech/urgent, och `SileroGate` får alltid sin
inbyggda tröskel `0.5` (`sileroGate.ts:11-14`). Konsekvens: VAD:ens viktigaste
parameter går inte att justera i drift utan att bygga om frontend — och
`LIVE_SPEECH_VAD_THRESHOLD` i `.env.example` ljuger om vad den gör.

### F2. Ingen hysteres eller utjämning på Silero-sannolikheten

`SileroGate.speech` jämför varje fönster rakt mot tröskeln
(`sileroGate.ts:27`). Runt 0.5 fladdrar sannolikheten i brusiga rum, och varje
falskt "tyst"-fönster nollställer `TurnVad.above`-räknaren
(`turnVad.ts:29-31`), som kräver två fönster i rad (≈64 ms) för att öppna.
Korta ord ("ja", "nej", "okej") i brus är den exakta fail-mod som
turssegmenteringen är byggd för att klara — men ett fladdrande
sannolikhetsvärde gör att `above` aldrig når 2. Standardlösning: hysteres
(gå in vid högre tröskel, gå ur vid lägre) plus en kort utjämning (t.ex.
EMA över 2–3 fönster).

### F3. Modellen laddas per session — tal i uppkopplingsfönstret kastas

`createSpeechVad` (`speechVad.ts:8-15`) körs per `session.ready` och skapar en
ny `InferenceSession` (`sileroModel.ts:14-18`): dynamisk import av
onnxruntime-web + WASM-laddning + 2,3 MB-modell varje gång. Medan detta pågår
är `vad === null` och `hear()` kastar alla mikrofonramar
(`useLiveSpeechConversation.ts:272-275`; samma i
`useSmeGroupVoice.ts:213-220`). En användare som börjar prata direkt efter
uppkoppling förlorar de första hundradelarna till sekunderna — och vid
återanslutning (t.ex. efter idle-timeout) händer det igen.

### F4. Inferens på main-tråden

ONNX-inferensen körs med `numThreads = 1` på main-tråden
(`sileroModel.ts:17`) och varje fönster awaitas sekventiellt i `hearing`-kedjan
(`useLiveSpeechConversation.ts:279-288`). Ett 512-fönster är billigt, men på
svaga maskiner (eller med en låst UI-tråd) växer kön av 30 ms-ramar och
end-to-end-latensen ökar. `env.wasm.proxy` (automatisk worker i äldre
onnxruntime-web) finns inte i 1.30; att flytta modellen till en egen Web
Worker kräver medvetet arbete. Ska mätas innan det görs.

### F5. Resampling utan lågpassfilter — aliasing in i både VAD och STT

Mikrofonen fångas vid enhetsfrekvensen (typiskt 48 kHz). Två parallella
linjära interpolationer utan lågpassfilter sker: 48k→16k för Silero
(`sileroGate.ts:41-53`) och 48k→24k för det skickade ljudet
(`liveVoiceAudio.ts:51-76`). 3:1-nedsamplingen in i VAD:en är den grövsta.
Enkelt alternativ: skapa capture-kontexten med `new AudioContext({ sampleRate:
24_000 })` så att webbläsarens egen (filtrerade) resampler gör 48k→24k en gång;
Silero får sedan 2:3 (24k→16k), vilket linjär interpolation klarar betydligt
renare. Måste verifieras i Safari/Firefox innan det införs.

### F6. VAD-falskpositiv på brus → feltoast till användaren

När Silero öppnar en tur på brus (tangentbord, hosta) transkriberas inget och
servern svarar `empty_transcript` (retryable). Klienten visar då en
"transkriberingsfel"-toast (`useLiveSpeechConversation.ts:397-406`). Beteendet
är självläkande men upplevs som ett fel. Rotfixen är F1/F2 (färre
falskpositiver); oberoende av det borde en retryable `empty_transcript` inte
toastas som ett hårt fel.

### F7. Dokumentationsdrift

`backend/.env.example:141` anger `LIVE_SPEECH_VAD_MIN_SPEECH_MS=300` medan
koddefaulten är 120 (`live_speech_settings.py:17`) och specen
(`docs/specs/live-voice-workspace-chat.md`) beskriver 120 ms. `threshold` i
samma block beskriver dessutom en parameter som inte längre gör något (F1).

### F8. Test- och mätgap

- `turnVad.test.ts` (6 tester) och `sileroGate.test.ts` (3 tester) täcker
  segmentering, fönstring och resamplinglängd — men inget test kopplar
  serverkonfig → SileroGate/SpeechVad (därför överlevde F1).
- Ingen offline-evaluering av modellen: inga mätningar av falska starter,
  missade starter eller öppningslatens. Alla tröskeländringar blir idag
  tyckande, inte mätbara.
- Modellfilens proveniens/licens (`frontend/public/vad/silero_vad.onnx`) är
  inte dokumenterad i repot.

Inga buggar hittades i turssegmenteringen (TurnVad) eller i PCM-protokollet:
`encodePcm16` resamplar till 24 kHz vilket stämmer med `audio.start`-deklarationen.

## 3. Förslag (prioriterade)

| # | Förslag | Effekt | Insats |
| --- | --- | --- | --- |
| P1 | **Preload + singleton för Silero-modellen.** Ladda sessionen en gång (modulnivå), `reset()` mellan sessioner; starta laddningen när röst-UI:t mountas. Buffra ≤250 ms preroll-ramar medan modellen laddas så att tidigt tal inte kastas (F3). | Hög: inget tappat tal vid uppstart/återanslutning | Liten |
| P2 | **Hysteres + utjämning + serverstyrd tröskel.** Ersätt den döda `threshold` med `silero_threshold` (t.ex. 0.5) och `silero_exit_threshold` (t.ex. 0.35) plus kort EMA i `SileroGate`; skicka via `vad_client_config()` och koppla in i `speechVad`. Rensa bort `live_speech_vad_threshold` (F1, F2). | Hög: färre falskpositiver och färre missade korta ord, justerbart i drift | Liten–medel |
| P3 | **Capture vid 24 kHz.** `new AudioContext({ sampleRate: 24_000 })` för capture-kontexten; Silero-resamplar 2:3. Verifiera Safari/Firefox (F5). | Medel: renare ljud in i STT och VAD | Liten, med webbläsarverifiering |
| P4 | **ONNX i Web Worker.** Mät först jank/eftersläpning (p95) på lågprestandahårdvara; bygg bara om det behövs (F4). | Medel (om uppmätt) | Stor |
| P5 | **Mjukare `empty_transcript`.** Retryable tomma transkript toastsar inte som fel (F6). | Medel (UX) | Liten |
| P6 | **Offline-VAD-eval.** Korta inspelningar med etiketterade taltider; kör samma ONNX-modell i Node; mät missad start, falsk start och öppningslatens vid olika trösklar/hysteres/hangover. Ger evidensbas för P2 och för ev. hangover-sänkning (400–600 ms) (F8). | Hög (process) | Medel |
| P7 | **Konfigurationsstädning.** env.example + spec synkade (min_speech 120), dokumentera modellens källa/licens (F7, F8). | Låg–medel | Liten |

Rekommenderad ordning: P1 + P2 + P5 + P7 som snabbvinst (samma PR-serie,
frontend + backend + env), därefter P6 som grund för att A/B:a trösklarna och
eventuellt sänka hangover. P3 och P4 efter mätning.

## 4. Öppna frågor

- Har ni observerat konkreta symptom? (missade "ja/nej", falska starter vid
  brus, toast "transkriberingsfel", trög start efter anslutning) — styr
  prioriteringen mellan P1/P2/P5.
- Accepteras en hangover-sänkning mot snabbare "thinking"-övergång, givet att
  den måste mätas via P6?
- Måste VAD-besluten förklaras i UI:t (t.ex. modellspår), eller räcker
  serverloggar?
