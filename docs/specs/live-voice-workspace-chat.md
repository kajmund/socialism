# Live Speech i SME-chatten

## Beslut

Live Speech är ett röstgränssnitt till den befintliga SME-expertchatten. Det är
inte en separat dialogmotor.

```text
Browser PCM + lokal VAD
  → /ws/live-speech
  → OpenAI Realtime transcription (gpt-live-transcribe, turn_detection=null)
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
strömmande assistenttext och TTS-ljud.

En processlokal generation äger varje aktiv session. En ny session för samma
användare och workspace återkallar den föregående. V1 återupptar inte en
halvfärdig ljudtur efter socketdrop.

## VAD och avbrott

Browsern kalibrerar en enkel energibaserad VAD, behåller cirka 250 ms pre-roll
och committar efter cirka 600 ms tystnad. En tur bekräftas efter cirka 120 ms
sammanhängande tal, samma gräns som öppnar STT, så att korta ord som "ja" och
"okey" blir en tur. Kortare brus kastas. `stopp`, `nej` och `vänta` klassas
så fort transkriptet finns. OpenAI-sessionen
konfigureras alltid med `turn_detection: null`.

Talstart under uppläsning avbryter inte ensamt. Servern klassificerar
partial-transkript: korta lyssnarsignaler fortsätter turen, medan en fråga,
korrigering eller urgent-fras skickar `turn.cancel`, tömmer browserns ljudkö
och behåller den nya turens pre-roll.

## Lyssnarsignal och framstegstal

När sessionen öppnas säger Snabb-modellen först en kort replik utifrån de
senaste intervju-meddelandena. Den går inte via `execute_expert_turn` och
använder inte Mem0-sökning. När användaren har talat längre än cirka fyra
sekunder kan samma modell läsa upp en kort lyssnarsignal. Den sparas inte i
chatten. Medan ett verktyg eller en sammanställning pågår kan den säga vad
som faktiskt händer, utan fasta fraser och utan att skriva historik.
Huvudsvaret klipper det talet. Ett textmeddelande i samma samtal avbryter
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
