# Live Speech i SME-chatten

## Beslut

Live Speech är ett röstgränssnitt till den befintliga SME-expertchatten. Det är
inte en separat dialogmotor.

```text
Browser PCM + Silero VAD
  → /ws/live-speech
  → OpenAI Realtime transcription (gpt-live-transcribe, turn_detection=null, near_field)
  → accept_expert_turn + execute_expert_turn
  → befintlig Jev-routing, promptar, historik och verktyg
  → SpeechSegmenter
  → ElevenLabs AsyncElevenLabs text_to_speech.stream
  → binär PCM tillbaka på samma Socialism-WebSocket
```

ElevenLabs Agents används inte av SME-röstknappen. ElevenLabs används endast
för TTS. Persona-kompositörens separata live-voice-funktion ingår inte i denna
ändring.

## Kanonisk dialogväg

Sluttranskript anropas som en vanlig expertturn genom
`app.services.sme_expert_turns.execute_expert_turn`, som i sin tur använder
`stream_library_chat_turn`. Jev väljer `fast`, `balanced` eller `deep` genom
`expert_reasoning_turn`; klienten skickar inget modelläge. Samma
`persona_messages`, expertminne, workspace state, promptfält och verktyg används
för text och röst.

Partial-transkript är endast visningsdata. Final användartext och assistenttext
sparas en gång av expertturnen. Vid barge-in avbryts generator och TTS; den
text som hann genereras sparas med `interrupted=true`.

## Protokoll

`/ws/live-speech` autentiseras med samma `access_token` som övriga sockets.
Kontrollhändelser är JSON och ljud är mono PCM16, 24 kHz, little-endian.
Klienten skickar `session.start`, `audio.start`, binära frames och
`audio.commit`. Servern svarar med sessionstillstånd, partial/final transcript,
strömmande assistenttext och TTS-ljud. `audio.output.start` och
`audio.output.end` bär `response_id` och `generation_id`; varje svar eller
aside får en ny generation, och klienten spelar bara ljud inom en öppen start.
Äldre generationer släpps när en ny start har kommit.

En processlokal generation äger varje aktiv session. En ny session för samma
användare och workspace återkallar den föregående. V1 återupptar inte en
halvfärdig ljudtur efter socketdrop.

## VAD och avbrott

Browsern klassar tal med Silero VAD, behåller cirka 250 ms pre-roll
och committar efter cirka 600 ms tystnad. En tur bekräftas efter cirka 120 ms
sammanhängande tal, samma gräns som öppnar STT, så att korta ord som "ja" och
"okey" blir en tur. Kortare brus kastas. Silero-sannolikheten utjämnas kort
och gatas med hysteres: tal öppnar vid `LIVE_SPEECH_VAD_SILERO_THRESHOLD`
(default 0.5) och stänger först under `LIVE_SPEECH_VAD_SILERO_EXIT_THRESHOLD`
(default 0.35), så att enstaka fönster runt gränsen inte flippar turen.
Trösklarna skickas per session i `session.ready` tillsammans med pre-roll,
hangover och talgränserna. Silero-sessionen laddas en gång per sidladdning och
förladdas när röstsessionen startar; mikrofonramar buffras (≤250 ms) tills
modellen är klar, så tidigt tal inte kastas. Inferensen körs i en dedikerad
Web Worker så att ONNX aldrig blockerar UI-tråden. Mikrofonen fångas vid
24 kHz: webbläsarens filtrerade resampler gör 48k→24k en gång, Silero
resamplar 2:3 till 16 kHz och PCM:en går ut som den är. En retryable
`empty_transcript`
(VAD öppnade på brus) återgår tyst till lyssnande utan feltoast.
`stopp`, `nej` och `vänta` klassas
så fort transkriptet finns. OpenAI-sessionen
konfigureras alltid med `turn_detection: null` och `noise_reduction: near_field`.
Webbläsarens brusreducering är avstängd så att bara OpenAI-filtret ligger på
strömmen. Eko-borttagning är kvar.

Prompt och basnyckelord kommer från promptkatalogen. När ett dokument visas
läser servern dess textenheter och skickar en ny `session.update` med begreppen
som nyckelord, utan att starta om transkriberingen. Klienten skickar bara
käll-id, aldrig termerna.

Talstart under uppläsning avbryter inte ensamt. Servern klassificerar
partial-transkript: korta lyssnarsignaler fortsätter turen, medan en fråga,
korrigering eller urgent-fras skickar `turn.cancel`, tömmer browserns ljudkö
och behåller den nya turens pre-roll. Klienten stoppar också lokalt: ett
urgent partial (`stopp`, `nej`, `vänta`, ...) tömmer kön och skickar
`turn.cancel` direkt utan att vänta på serverns klassificering.
Öppningsrepliken kan tystas på samma sätt.

## Lyssnarsignal och framstegstal

När sessionen öppnas säger Snabb-modellen först en kort replik utifrån de
senaste intervju-meddelandena. Den går inte via `execute_expert_turn` och
använder inte Mem0-sökning. När användaren har talat längre än cirka fyra
sekunder kan samma modell läsa upp en kort lyssnarsignal. Den sparas inte i
chatten. När användaren har svarat och experten inte har sagt något på 50
millisekunder sägs en kort framstegsreplik. Så fort ett verktyg körs sägs vad som
händer, utan extra väntan. Fraserna är inte fasta och skrivs inte i historiken.
Huvudsvaret klipper det talet. I en rösttur läses bekräftelserepliken från
verktygsvalsanropet upp innan verktygsepilogen körs, så första ljudet inte
väntar på verktygen. Ett textmeddelande i samma samtal avbryter
den aktuella turen men lämnar röstsessionen öppen.

## Säkerhet och livscykel

Providerhemligheter stannar i backend. Råljud lagras inte. Workspace,
kundscope och expert verifieras innan provideranslutningen öppnas och
databastransaktionen avslutas före externa anrop. Stop, socketdrop, timeout och
providerfel stänger STT, LLM och TTS. Redan accepterade bakgrundsjobb fortsätter
i jobbdomänen.

## Konfiguration

Se `backend/.env.example` för `LIVE_SPEECH_*`, `OPENAI_API_KEY`,
`ELEVENLABS_API_KEY` och `ELEVENLABS_VOICE_ID`. Ingen provider- eller
modellfallback används. `gpt-realtime-whisper` kan väljas med samma inställning
för ett uttryckligt jämförelseprov, men ersätter inte lokal VAD och aktiveras
inte automatiskt.

## Verifiering

Automatiska tester täcker kontrollschema, sessionersättning, OpenAI-event,
segmentering, VAD-trösklar, backchannel, lyssnarsignal och framstegstal.
Leverantörsacceptans ska dessutom verifiera svensk transkription, svensk
röst, PCM-stream, abrupt cancel och uppmätta pipeline-latenser på riktiga
mikrofoner. Latensmålen skrivs inte som uppmätta förrän de kommer från ett
riktigt samtal.
