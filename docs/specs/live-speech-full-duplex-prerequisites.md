# Live Speech Full Duplex — inventering av förutsättningar

Status: inventering genomförd 2026-10-18 (läs-only). Underlag för
[live-speech-full-duplex.md](live-speech-full-duplex.md), avsnitt 8.

Arbetsträdet är branch `fix/sme-group-chat-voice` **med oincheckade ändringar**
(213 filer, bl.a. live speech). Inventeringen beskriver filerna som de ligger på
disk just nu, inte senaste commit. Testläge vid inventeringen:

- backend: `uv run pytest tests/test_live_speech.py
  tests/test_live_speech_conversation.py tests/test_sme_group_voice_barge.py`
  → 48 passed,
- frontend: `pnpm vitest run` på live speech-filerna →
  6 filer / 28 tester passed.

## 1. Slutsats

Specen beskriver en resa "från traditionell turbaserad kommunikation till
konversationell full duplex". Den viktiga upptäckten är att den inbyggda
`socialism`-providern för SME-expertchatten **redan är långt förbi turbaserad**:

- kontinuerlig lyssning även när AI:n talar,
- regelbaserad + LLM-bekräftad barge-in-klassificering (backchannel vs avbrott),
- lyssnarsignaler, öppningsreplik och framstegstal från Snabb-modellen,
- strömmande segment-TTS (ElevenLabs) med fras-cache och avbrottstoken.

Viktig nyans: "strömmande" gäller **textsegmenteringen efter att svaret finns**.
I det vanligaste SME-läget (verktyg påslagna) batchas hela svaret innan första
ljudet — se §4.6. Barge-in är textbaserad, inte akustisk.

Det som **saknas** är i huvudsak:

1. **Spekulativ exekvering** (spec §6, steg 6). Finns inte i live-vägen.
2. **Explicit generationsidentitet på ljudsegment** (`response_id` +
   `generation_id`, §5). Identiteten är idag `turn_id` + `sequence` + interna
   heltals-token.
3. **Inkrementell TTS i verktygsläget.** `acknowledge_expert_tools` +
   `complete_tool_episode` ger hela svaret som ett chunk; första ljudet kan
   därför inte börja förrän hela svaret genererats (§4.6).
4. **Central Conversation Controller med de sju tillstånden** (§3). Turtagningen
   ägs idag implicit av `LiveSpeechRuntime`/`LiveSpeechCues` med fem strängtillstånd.
5. **Mätning av latensmålen** (§7) mot riktig mikrofon och nätverk. Mätpunkter
   loggas redan, men inga p50/p95/p99-värden är accepterade.
6. **Fas 2**: verkligt överlappande dialog och dynamisk omplanering (steg 7).
   Grupprösten har ordet-givning och handuppräckning, men inte samtidigt tal.
7. Verifiering att AI:n **inte transkriberar sin egen uppspelning** (acceptans 2)
   i ett riktigt samtal. AEC är på, men leverantörsacceptansen är ännu bara
   transportverifierad.

## 2. Vilka ytor specen träffar

Repot har tre röstytor:

| Yta | Provider/protokoll | Används av |
|---|---|---|
| Persona/messenger live voice | Gemini eller ElevenLabs Agents (signed URL, webbläsaren pratar direkt med providern) | Persona-kompositören, Messenger |
| **SME-expertchattens röst** | **`socialism`**: `/ws/live-speech`, PCM via Socialism, ElevenLabs endast TTS | SME-chatten (expert) |
| SME-gruppröst | `socialism`: `/ws/sme-group-voice`, floor/hand-styrd TTS | Expertpaneler |

`/ws/live-speech` kräver uttryckligen `live_voice_provider == "socialism"`
(`backend/app/api/live_speech.py:71-73`), och frontend väljer klient efter
samma fält (`SmeMessengerPage.tsx:91-93,150-153`). Specens komponenttabell
(JEV, Overgraph, mem0, befintlig tool-router, ElevenLabs som *TTS*) matchar
endast SME-expertchatten. Persona- och Agents-ytorna går via leverantörens egen
agentarkitektur och använder inte JEV, Overgraph eller mem0 i samtalet.
Gruppen är den enda befintliga grunden för Fas 2:s flera experter, men den är
turordnad med floor och hand, inte överlappande.

Viktigt: Fas 1-kraven (Jev-routing, modellväxling, verktygsrouter) kan bara
uppfyllas i socialism-vägen; den externa provider-vägen har ingen server-side
routing alls. Specen blandar därför två arkitekturer — arbetet hör hemma i
`LiveSpeechRuntime`.

## 3. Befintlig arkitektur

```text
Mikrofon (AudioContext, begärd 24 kHz; faktisk rate läses av webbläsaren,
echoCancellation på)
  → pcmCapture.worklet.ts (30 ms-frames)
  → Silero VAD v5 i Web Worker (512 samples @16 kHz, smoothing 0,4,
    hysteres 0,5/0,35) → turnVad.ts (preroll 250 ms, hangover 600 ms,
    min tal 120 ms, urgent 120 ms)
  → VAD-gate: endast talsegment skickas som PCM16 24 kHz
  → /ws/live-speech (audio.start / binära frames / audio.commit)
  → OpenAITranscriptionStream (gpt-live-transcribe, turn_detection=null, near_field)
  → LiveSpeechRuntime
      ├─ partial  → LiveSpeechCues.on_partial → SpeechBarge (ignore/barge/wait)
      └─ final    → execute_expert_turn
                      (Jev: fast/balanced/deep, befintliga verktyg, mem0/Overgraph)
  → SpeechSegmenter (första mål 110 tecken, max 220)
  → ElevenLabsTts (eleven_v4_turbo, pcm_24000, fras-cache på disk)
  → SpeechResponseCoordinator (audio.output.start/end, token, pacing ≤0,4 s)
  → PCM16 tillbaka på samma socket
```

## 4. Inventering enligt §8

### 4.1 Streaming-STT och ljudtransport

**Finns.** Frontend fångar 30 ms-ramar i en AudioWorklet
(`frontend/src/components/chat/pcmCapture.worklet.ts:13`), kör Silero VAD
lokalt och skickar endast tal-PCM som PCM16 mono 24 kHz. Upplänken är alltså
VAD-gatead, men gaten är oberoende av om AI:n spelar — mikrofonen är öppen
under uppspelning (`useLiveSpeechConversation.ts:325-351`). En pre-VAD-buffert
på 250 ms tar hand om tal innan Silero-modellen hunnit laddas
(`useLiveSpeechConversation.ts:46,299-312`).

Servern (`backend/app/api/live_speech.py:175-196`) tar emot antingen binära
PCM-frames eller JSON-kontroll. Frames valideras (`≤ 9600 byte` = 200 ms),
skickas vidare till OpenAI Realtime-transkription
(`intent=transcription`, `max_retries=0`, `turn_detection: null`,
`noise_reduction: near_field`) och buffras inte på servern
(`backend/app/services/openai_live_transcription.py:132-175`). `audio.commit`
committar buffer; final väntas i 12 s innan `stt_final_timeout`
(`live_speech_settings.py:9`). `stt.focus` byter nyckelord (max 24) mitt i
sessionen utan att återansluta (`live_speech_runtime.py:124-135`).

Tidiga latensmätpunkter loggas: `first_partial`, `final_transcript`,
`first_llm_delta`, `first_tts_audio` (`live_speech_runtime.py:271-280,
360-367, 464-471`).

**Begränsning:** ingen reconnect/resume. Vid socketdrop stängs sessionen
(`useLiveSpeechConversation.ts:160-162`); en halvfärdig ljudtur återupptas
inte. Ingen frontend-mätning av latens (`userActivity` är en stubbe).

### 4.2 VAD och barge-in

**VAD finns i webbläsaren.** Silero VAD v5 (ONNX, MIT) körs i en dedikerad
Web Worker med en delad session per sida
(`frontend/src/products/sme/sileroModel.worker.ts:29-37`,
`sileroModel.ts:12-20`); 512-samplersfönster vid 16 kHz, smoothing 0,4 och
hysteres (öppna 0,5 / stäng 0,35) i `sileroGate.ts:14-42`. `TurnVad` kräver
två talande 30 ms-frames i rad (≈60 ms) för att öppna, håller 250 ms preroll
och committar efter 600 ms tystnad (`turnVad.ts:30-74`). Trösklarna kommer från
servern i `session.ready` (`backend/app/live_speech_settings.py:50-59`).
Genomförd VAD-utredning: [vad-improvements-investigation.md](vad-improvements-investigation.md)
(utredningen är äldre än arbetsträdet: dess P4 om ONNX i worker är nu
genomförd).

**Barge-in finns och ligger nära specens tabell — men den är textbaserad och
backend-ägd.** `backend/app/services/live_speech_backchannel.py` klassificerar
partial/finaltranskript medan assistenten är aktiv:

- `interruption`: `stopp`, `nej`, `vänta`, `stop`, `wait`, `no` samt
  "men"-korrigeringar (`:22, 190-194`),
- `backchannel`: `mm`, `ja`, `precis`, `just det`, `okej`, … (+ tidsgräns
  1200 ms),
- `new_question`: frågetecken eller frågeord,
- `uncertain`.

Vid `wait` startas en LLM-bekräftelse (Snabb-profil, 0,35 s timeout) parallellt
med en 300 ms "confirm beat" (`live_speech_backchannel.py:96-111`). **Om LLM:en
inte hinner klart tolkas `uncertain` som stopp** — en medveten regel med risk
för falska stopp. Frontend klassificerar inget själv:
`transcript.backchannel` ignoreras helt (`useLiveSpeechConversation.ts:221-222`).

**Stoppvägen** är `SpeechBarge.consider` → `LiveSpeechCues.barge_in` →
`LiveSpeechRuntime.cancel_turn`: sätter cancel-event, invaliderar coordinatorns
uppspelningstoken, avbryter tur-tasken, **sparar avbruten tur i databasen** och
skickar därefter `assistant.cancelled` (`live_speech_runtime.py:180-220`).
Webbläsaren rensar ljudkön först när `assistant.cancelled` anländer
(`useLiveSpeechConversation.ts:243-246`).

**Begränsningar:**

- Ingen akustisk barge-in (ingen energi-/ljudklassificering, ingen jämförelse
  mot uppspelad PCM); AEC är enbart webbläsarens constraint.
- UI-knappens `cancel()` rensar lokalt direkt, men VAD-utlöst avbrott kräver
  STT-partial + klassificering + WS-tur **och** att den avbrutna turen
  persisterats innan `assistant.cancelled` skickas. Det gör att lokal tystnad
  inte är garanterat < 100 ms (specens §4/§7).
- Öppningsrepliken kan inte avbrytas: `assistant.opening` sätter inte
  `currentTurn`, så `cancel()` är en no-op medan den spelas
  (`useLiveSpeechConversation.ts:141,225-228`).
- `audio.cancel` accepterar `turn_id` men använder det inte
  (`schemas/live_speech.py:35-37` vs `api/live_speech.py:206-207`).

### 4.3 ElevenLabs och ljudbuffring

**Strömmande TTS med segment.** `SpeechSegmenter` delar LLM-texten vid
meningsgränser och skickar ett segment i taget till
`AsyncElevenLabs.text_to_speech.stream` (`eleven_v4_turbo`, `pcm_24000`)
(`speech_segmenter.py:75-122`, `elevenlabs_tts.py:22-32`).
`SpeechResponseCoordinator` äger en TTS-ström i taget för huvudrepliker och
asides (lyssnarsignal, öppning, framsteg), annonserar
`audio.output.start`/`audio.output.end` per segment med `turn_id` + `sequence`
och pausar om ljudet ligger mer än 0,4 s före realtid
(`live_speech_coordinator.py:91-138`). Fras-cache på disk (SHA-256 av
model|voice|format, språk, fras; single-flight, LRU) — se
[tts-cache.md](../guides/tts-cache.md) och `tts_cache.py`. Ordcache utreddes
och avvisades: [tts-word-cache.md](../guides/tts-word-cache.md).

**Begränsningar:**

- Segmentets identitet är `turn_id` + `sequence` + interna token
  (`_aside_token`, `_playback_token`). JSON-händelserna bär
  `voice_session_id` + `generation` från sessions-leasen
  (`api/live_speech.py:119-133`, `live_speech_sessions.py:15-64`), men den är
  sessionsscoped och läses inte av klienten. Ingen `response_id`/`generation_id`
  per svar eller segment (§5).
- Frontend ignorerar `audio.output.end` och har ingen segmentmedveten kö;
  `PcmQueue` är en platt PCM-kö utan metadata
  (`pcmQueue.ts:4-33`, `useLiveSpeechConversation.ts:241-242`). Uppspelningen
  antar 24 kHz hårdkodat; `session.ready.audio_format` läses inte
  (`useLiveSpeechConversation.ts:332`, `pcmQueue.ts:10`).
- Gruppvägen segmenterar inte: `speak_as` skickar hela svaret till ett enda
  TTS-anrop (`sme_group_voice_runtime.py:241-271`).

### 4.4 Jev-routing och verktygsrelevans

**Återanvänds rakt igenom.** En finaltranskription går som en vanlig
expertturn genom `execute_expert_turn` → `stream_library_chat_turn`. Jev
bedömer turen med promptfältet `chat.expert.reasoning_assessment` och
`expert_reasoning.py` väljer deterministiskt `fast`, `balanced` eller `deep`;
timeout/fel/ogiltigt svar ger Balanserad. Ett verktygsresultat kan höja
profilen, aldrig sänka den. Se [expert-reasoning-route.md](../guides/expert-reasoning-route.md)
och [expert-chat-reasoning-episode.md](expert-chat-reasoning-episode.md).

**Jev används även för röstens småprat:** öppningsreplik, lyssnarsignal,
väntreplik och framstegstal genereras av Snabb-profilen med 1,5 s timeout
(backchannel-bekräftelsen 0,35 s) via `bound_expert_profile("fast")`
(`live_speech_phrases.py:84-135`). Jev ligger alltså **inte** i den omedelbara
stoppvägen, vilket är rätt enligt §7.

**Samma Jev-request ger även verktygsrelevans.** `document_tool_retrieval.py`
låter Jev poängsätta varje verktyg mot användarmeddelandet; scoren skrivs in i
verktygsbeskrivningen som `jev_relevance` och topp-k filtreras. När både
profilrouting och verktygsretrieval är på går frågorna i **samma** Jev-anrop
(`expert_reasoning_turn.py:155-224`) — den enda befintliga optimeringen.

**Latens:** Jev-timeouten är 2,0 s för både routing och verktygsretrieval, och
en delad request tar `max()` av dem. Repot har en mätt median på **290,4 ms**
för post-result-Jev ([expert-prompt-routing.md](expert-prompt-routing.md)),
vilket ligger över specens ~120 ms. Varje anrop skapar dessutom en ny
`httpx.AsyncClient` (`jev/system.py:198-210`) — ny TCP/TLS-handskakning per
gång. Jev-fel ger Balanserad eller hela verktygskatalogen utan filtrering;
dokumenterat, men värt att mäta innan latensmålen sätts.

Gruppvägen använder Jev på ett annat sätt: `GroupVoiceSession` beslutar om
handuppräckning och floor via Jev-sannolikheter
(`sme_group_voice.py:182-231`).

### 4.5 Snabb och resonerande modell

**Delvis.** Den snabba modellen körs redan parallellt med turen — men bara som
samtalsglue (öppning, lyssnarsignal, väntreplik, verktygsframsteg), inte som en
egen svarsväg. Huvudsvaret genereras av den Jev-routade profilen och går via
samma `execute_expert_turn` som textchatten. Modellvalet sker i
`llm/selection.py` mot `llm_configurations` (ingen hårdkodad modell i
live-vägen); default är Cerebras `gpt-oss-120b`, DeepSeek finns för A/B.

Modellkatalogen har fyra profiler (`deepseek-flash`, `deepseek-v4-pro`,
`gpt-oss-120b`, `qwen-3.8-27b`). Jev-routningen matchar en
`llm_configurations`-rad på `selection_role`; det förutsätter att tabellen är
uppseedad. Utan rader med `enabled_for_auto` faller allt tillbaka på den
globala defaultmodellen, och en djup-routning utan deep-rad faller tyst
tillbaka på default. Det finns inget modellfält i live speech-protokollet
eller `LiveSpeechScope`, så modellen kan inte bytas per samtal.

**Djup blockerar turen:** routing + minnessökning inväntas innan LLM-strömmen
skapas (`expert_turn_prefetch.py:38-53`), och det finns ingen parallell
snabbmodell som börjar prata medan Djup tänker.

**Qwen** används bara som Mem0-vision och i experiment, inte som snabb
samtalsmodell. Specens "Qwen/OSS – snabb samtalsmodell" är alltså en
namngivningsskillnad att reda ut, inte en ny arkitektur.

**Kritisk begränsning:** när verktyg är påslagna (det vanliga SME-läget) är
LLM-vägen i praktiken batchad — se §4.6. Då finns ingen parallell "börja
svara"-väg för själva innehållet, bara glue-fraserna.

### 4.6 Asynkrona verktygsanrop

**Delvis.** Verktygskatalogen byggs av workspace-verktyg + persona-verktyg
(`persona_chat.py:337-357`). Klientverktyg (`show_document`, `show_relations`,
`focus_anchor`, …) exekveras i frontend och skickas envägs som
`workspace.tool` (`live_speech_runtime.py:422-427`); servern får **inget
resultat tillbaka**. Serververktyg (sök, dokument, research, …) körs inuti
turen via den befintliga verktygsrunnern, batchas med `asyncio.gather`, har
45 s timeout och respekterar turn-cancel-eventet
(`expert_async_tools.py:401-412`, `expert_tool_run.py:27-46,49-81`). Episoden
kan göra upp till fyra verktygsrundor (`expert_reasoning_episode.py:208-260`),
och klientverktyg emit:as först **efter** att hela svaret är klart
(`persona_chat.py:416-419`) — UI-effekter (dokument, fokus, markeringar) kommer
alltså inte mitt i turen. `asyncio.to_thread`-verktyg (sök, mem0) kan inte
avbrytas av task-cancel.

**Progress till användaren:** `bind_tool_progress` → `LiveSpeechCues` →
`assistant.waiting` + talad fras när ett verktyg startar
(`live_speech_cues.py:183-186,251-303`).

**Kritisk begränsning — batchning:** i `stream_reply_as_persona` körs först
`acknowledge_expert_tools` (icke-strömmande), och om det finns verktygsanrop
körs `complete_tool_episode` innan **hela svaret yieldas som ett chunk**
(`backend/app/llm/chat.py:315-335`). `SpeechSegmenter` får då ett stort delta och
segmenterar efteråt; det betyder att första ljudet inte kan börja förrän hela
svaret genererats, och att första-ljud-latensen blir hela modell+verktygstiden.
Det finns heller ingen
kanal för att injicera ett sent verktygsresultat i en pågående rösttur —
progress-fraserna är kosmetiska, inte en resultatväg.

Redan accepterade **bakgrundsjobb** i jobbdomänen fortsätter efter avbrott,
men ett verktygsanrop i en avbruten tur avbryts. Det är delvis uppfyllt mot
acceptans 7.

### 4.7 Avbrott och cancellation

**Finns i flera lager:**

- turn: `cancel_turn` (cancel-event, token, task.cancel, avbruten tur sparas
  med `interrupted=true`) — `live_speech_runtime.py:180-220`,
  `live_speech_history.py`,
- TTS: coordinatorns token + browser `clearPlayback`/`dropIncomingAudio`,
- STT: `audio.cancel` + `stt.clear()`,
- session: `session.stop`, idle-timeout 120 s, TTL 3600 s, ny session för samma
  användare/workspace återkallar den föregående (close-kod 4001),
- databas: ingen transaktion hålls över externa anrop (admission/fence-mönstret
  i `live_speech_admit.py`; se `docs/guides/live-voice-workspace-chat.md`).

**Begränsningar:**

- Ingen svars-/segmentgeneration. Skyddet mot föråldrade segment är
  server-token + `audio.output.start/end` + klientens boolska
  `dropIncomingAudio` (nollställs först vid nästa `audio.output.start`).
- `assistant.cancelled` skickas efter att den avbrutna turen persisterats
  (`live_speech_runtime.py:184-214`), vilket fördröjer klientens lokala stopp.
- Ingen reconnect/resume mitt i en tur.
- `asyncio.to_thread` (mem0, sök) och mem0-skrivningen efter turen cancellas
  inte; redan enqueue:ade workspace-jobb fortsätter.
- Mindre: `AudioCancel.turn_id` ignoreras; gruppens `_speaking_task` sätts
  aldrig (`sme_group_voice_runtime.py:79,123-125`); `tts_cache._read_hit` läser
  hela filen synkront på event-loopen (`tts_cache.py:151-153`).

### 4.8 Minne och kontext (mem0/OverGraph)

**mem0 läses på första-token-kritiska vägen.** `profile_with_memory` kör
`expert_memory_context` som egen task parallellt med Jev-routningen och
inväntar båda; sökningen har ingen egen timeout och `asyncio.to_thread` kan
inte avbrytas av task-cancel (`expert_turn_prefetch.py:38-53`,
`expert_memory_context.py`). Det kan fördröja första token obestämt.

**Skrivning sker efter turen** i en detached task
(`expert_memory_schedule.py`), så den blockerar inte samtalet.

**OverGraph** har två kataloger (`knowledge`, `memory`); mem0:s vektorlager är
OverGraph. Knowledge läses via verktyg (`search_knowledge`, `find_documents`,
`read_source`), inte som automatisk samtalskontext — det finns ingen
automatisk OverGraph-berikning per tur.

**Konsekvens för spekulativ exekvering:** en spekulativ läsning skulle behöva
en egen, avbrytbar väg; idag ligger både Jev och mem0 före LLM och startar
först efter final transcript.

## 5. Gap-analys mot specen

### 5.1 Fas 1-acceptanskriterier

| # | Kriterium | Status | Evidens/begränsning |
|---|---|---|---|
| 1 | Prata medan AI:n pratar | Finns | Mikrofonen är öppen under uppspelning; upplänken är VAD-gatead men oberoende av playback |
| 2 | AI:n transkriberar inte sin egen uppspelning | Delvis | AEC i webbläsaren + `near_field` + textligt eko-skydd; ingen referens-AEC, ej live-verifierat |
| 3 | "Mm/ja/precis" avbryter inte | Finns | `BACKCHANNELS` + tidsgräns + LLM-bekräftelse; tester finns |
| 4 | "Stopp" stoppar omedelbart | Delvis | `URGENT` → `interruption` utan LLM/JEV, men lokal tystnad sker efter WS-tur + persistering |
| 5 | Ny fråga mitt i AI-svar | Finns | `new_question` → barge; `_begin_turn` avbryter föregående |
| 6 | Gamla segment spelas inte efter avbrott | Delvis | Token + `dropIncomingAudio`; ingen svars-/segmentgeneration; öppningsrepliken kan inte avbrytas |
| 7 | Verktyg kan fortsätta i bakgrunden | Delvis | Bakgrundsjobb fortsätter; pågående verktyg i avbruten tur avbryts; klientverktyg är envägs |
| 8 | AI:n talar innan hela svaret finns | Delvis | Gäller utan verktyg; i verktygsläget batchas hela svaret (§4.6) |
| 9 | Jev-routing och verktygsarkitektur återanvänds | Finns | Samma `execute_expert_turn` som textchatten |
| 10 | Fungerar när Djup tar flera sekunder | Delvis | Vänt/lyssnar-fraser håller samtalet levande; ingen överlappande dialog |

### 5.2 Implementationsstegen

| Steg | Status | Kommentar |
|---|---|---|
| 1. Kontinuerlig mikrofon + AEC under AI-tal | Finns i grunden | `echoCancellation: true`, `noiseSuppression: false` (`liveSpeechMicrophone.ts:6-11`); AEC ej verifierad i `getSettings()` |
| 2. Intelligent barge-in | Finns | `live_speech_backchannel.py` + tester; textbaserad, `uncertain`→stopp vid LLM-timeout |
| 3. Central Conversation Controller | Delvis | Implicita tillstånd (`listening`, `thinking`, `speaking`, `paused`) i runtime/cues; ingen 7-tillståndsmaskin och ingen klient-side koordinator |
| 4. Strömmande TTS med segmentkö, generation-id, cancellation | Delvis | Segment + queue + cancellation finns; generation-id saknas; gruppvägen segmenterar inte; verktygsläget batchar |
| 5. Snabb modell parallellt med resonemangsmodellen | Delvis | Snabb används för cues, inte som parallell svarsväg |
| 6. Spekulativ läsning och verktyg | Saknas | Endast minnesparalllisering i textchatten (`expert_turn_prefetch.py`) |
| 7. Verklig överlappande dialog + omplanering | Saknas | Gruppröst har floor + hand, inte överlappning |

### 5.3 Fas 2

Grupprösten är en bit på vägen: `GroupVoiceSession` har floor, floor-orsak
("hand" eller "name"), handuppräckning och Jev-baserade hand-/floor-beslut
(`sme_group_voice.py:61-137,182-231`), och frontend har `raise_hand`/
`grant_floor`/`release_floor` (`useSmeGroupVoice.ts:329-343`). Det ger
"experter kan begära ordet medan andra pratar" i turordnad form. Det som
saknas är **samtidigt tal**, dynamisk omplanering av ett pågående svar och
överlappande deltagande.

### 5.4 Latensmål (§7)

| Mål | Mekanism idag | Mätläge |
|---|---|---|
| Lokal VAD-reaktion < 50 ms | Silero 512-fönster (≈32 ms) + två 30 ms-frames (≈60 ms); härledd start ≈90–120 ms | Instrumenteras inte i klienten |
| Stoppa lokal uppspelning < 100 ms | Knapp-`cancel()` lokalt direkt; VAD-barge kräver server-tur + persistering | Ej mätt |
| Identifiera tydligt avbrott < 200 ms | Regelklassificering på partial; LLM-bekräftelse endast för `uncertain` (300 ms-beat) | Loggas: `live_speech.backchannel_classified`, `live_speech.barge_in` |
| JEV-klassificering ~120 ms | Jev via `expert_reasoning_turn`; inte i stoppvägen. Mätt median post-result 290,4 ms, 2,0 s timeout, ny HTTP-klient per anrop | Loggas: `expert_chat.reasoning_routed` |
| Första naturliga respons < 500 ms | Väntreplik från Snabb (50 ms-beat, 1,5 s timeout) eller öppningsreplik | Loggas: `live_speech.waiting_phrase latency_ms` |
| Första innehållsbärande ljud < 1000 ms | `first_llm_delta` → segmenter → TTS; i verktygsläget först efter hela episoden | Loggas: `live_speech.first_tts_audio` |

Alla mätpunkter finns som enskilda loggrader; ingen sammanställning
(p50/p95/p99) och ingen klient-side tidsstämpel. Specen säger att målen ska
verifieras genom mätning — det är nästa steg innan något byggs om.

## 6. Risker och öppna frågor

1. **Dubbla runtimes.** En-expert- och gruppvägen är två separata runtimes som
   delar barge-in, fraser och coordinator men inte STT/TTS-orkestrering. En
   tredje väg (t.ex. spekulativ exekvering som egen loop) vore precis den
   parallella arkitektur specen förbjuder. Beslut behövs: utöka
   `LiveSpeechRuntime` eller bryt ut en gemensam kärna först.
2. **Var ägs Conversation Controller?** Specen säger att den ska äga
   turtagningen. Idag ägs den av runtime + cues + barge-modul tillsammans,
   och klienten har tre parallella statusunioner. Ska steg 3 bli en egen modul
   med de sju tillstånden, eller räcka det att formalisera befintliga tillstånd?
3. **"Qwen/OSS" i specen** motsvarar inte stacken (Cerebras gpt-oss-120b +
   DeepSeek). Ska specen justeras eller ska Qwen införas?
4. **Generation-id** kräver protokolländring (`audio.output.start` får
   `response_id`/`generation_id`) och klientvalidering. Ska gamla segment
   kastas på `turn_id` (idag) eller på generation?
5. **Barge-in utan falska stopp.** `uncertain` → stopp vid LLM-timeout kan
   avbryta mitt i ett ord. Ska osäker klassning hellre vänta tills final
   kommer, eller ska tidsgränsen höjas?
6. **Spekulativ exekvering** måste gå genom befintlig verktygsrouter och vara
   läs-only; frågan är vilka verktyg som är säkra att starta på partial
   (Overgraph-sök, dokumentsök) och hur resultatet matchas mot den slutliga
   frågan.
7. **Mätning**: latensmålen kräver riktig mikrofon, svensk transkription och
   nätverk. Ska mätningen ske lokalt eller i en representativ miljö, och vilka
   p50/p95/p99 accepteras för Fas 1?
8. **Oincheckat arbete**: 213 filer är ändrade i arbetsträdet. Innan
   implementation bör man veta vad som är på väg in, så att inventeringen inte
   bygger på mellanlägen (särskilt `live_speech.py`, `live_speech_settings.py`
   och frontend-hookarna).
9. **Jev på kritisk väg**: 2,0 s timeout och en ny HTTP-klient
   (TLS-handskakning) per anrop. En delad klient och/eller kortare timeout är
   billiga vinster, men måste mätas mot kvaliteten i routingbesluten.
10. **mem0 utan timeout på första-token-kritiska vägen**: sökningen kan fördröja
    första ljud obestämt och går inte att cancellera. Behöver egen timeout eller
    flyttas bort från första-token-vägen.
11. **Uppseedad `llm_configurations` krävs** för att Jev-routningen ska växla
    mellan Snabb/Balanserad/Djup; annars kör allt global default. Det bör ingå i
    acceptanstestet för Fas 1.

## 7. Rekommenderad fortsättning

1. **Bekräfta ytan** (SME-expertchatten) och att Fas 1 = befintlig
   `socialism`-provider, inte en ny motor. Grupprösten är startpunkten för
   Fas 2, inte en del av Fas 1.
2. **Mät först**: kör ett riktigt svenskt samtal och samla p50/p95/p99 för
   VAD-reaktion, stopp, avbrottsbeslut, första respons och första ljud. Lägg
   till klient-side tidsstämplar och mät Jev- och mem0-sökningens andel av
   första-token-latensen. Det avgör om steg 1–4 behöver ändras innan ny
   funktion byggs.
3. **Gör LLM-strömmen verkligt inkrementell i verktygsläget**: streama
   `complete_tool_episode` (eller tala en kort ack/lead-in medan verktygen
   körs) så att första ljudet inte väntar på hela episoden. Det är den
   enskilt största latensvinsten för Fas 1.
4. **Generation-id (steg 4 rest)**: lägg `response_id`/`generation_id` i
   `audio.output.start`, låt klienten kasta segment vars generation inte
   matchar aktiv tur, och använd `audio.output.end`. Små ändringar i schema,
   coordinator och frontend.
5. **Lokal nödstopp**: låt klienten känna igen `stopp`/`nej` i partialtexten
   och tömma kön omedelbart (parallellt med serverns beslut), samt gör
   öppningsrepliken avbrytbar. Det uppfyller §4:s "stoppa lokalt utan att
   invänta LLM eller JEV".
6. **Formalisera Conversation Controller (steg 3)**: lyft ut turtagningen ur
   runtime/cues till en explicit tillståndsmaskin med de sju tillstånden;
   behåll barge-modulen som beslutsfattare.
7. **Spekulativ läsning (steg 6)**: läs-only-verktyg startas på stabila
   partials, avbryts/markeras inaktuella vid ny partial, återanvänds endast när
   den slutliga frågan är förenlig.
8. **Fas 2**: först därefter överlappning och omplanering; bygg vidare på
   gruppröstens floor/hand-modell i stället för att skapa en ny.

## 8. Källor

Kod (arbetsträdet):

- `backend/app/services/live_speech_runtime.py` — STT, tur, TTS, cancel
- `backend/app/services/live_speech_cues.py` — lyssnarsignal, väntreplik, framsteg, barge-in
- `backend/app/services/live_speech_backchannel.py` — klassificering och stopp
- `backend/app/services/live_speech_coordinator.py` — en TTS-ström, token, `audio.output.*`, pacing
- `backend/app/services/live_speech_phrases.py` — Snabb-fraser och backchannel-LLM
- `backend/app/services/speech_segmenter.py` — textsegmentering
- `backend/app/services/openai_live_transcription.py` — OpenAI Realtime-transkription
- `backend/app/services/live_speech_admit.py`, `live_speech_history.py`, `live_speech_progress.py`, `expert_turn_cancel.py` — admission, avbruten tur, verktygsframsteg
- `backend/app/services/expert_tool_run.py`, `expert_async_tools.py`, `backend/app/llm/chat.py` — verktygskörning och batchning
- `backend/app/jev/system.py`, `backend/app/services/expert_reasoning.py`, `backend/app/services/document_tool_retrieval.py`, `backend/app/llm/selection.py` — Jev-routing, verktygsrelevans och modellval
- `backend/app/services/expertgranskning/memory.py`, `backend/app/services/expert_memory_context.py`, `backend/app/services/expert_memory_schedule.py`, `backend/app/services/overgraph/catalogs.py` — mem0/OverGraph
- `backend/app/api/live_speech.py`, `backend/app/schemas/live_speech.py` — WebSocket-endpoint och kontrollhändelser
- `backend/app/live_speech_settings.py` — VAD/TTS/backchannel-inställningar
- `frontend/src/products/sme/useLiveSpeechConversation.ts` — klientprotokoll, kö, cancel
- `frontend/src/products/sme/{sileroGate,sileroModel,sileroModel.worker,speechVad,turnVad,liveSpeechMicrophone,pcmQueue}.ts` — klient-VAD och ljud
- `frontend/src/components/chat/pcmCapture.worklet.ts` — 30 ms-ramar
- `frontend/src/components/chat/liveVoice.ts`, `geminiLiveProtocol.ts`, `elevenlabsLiveProtocol.ts` — externa provider-adaptrar
- `backend/app/services/sme_group_voice.py`, `sme_group_voice_runtime.py`, `frontend/src/products/sme/useSmeGroupVoice.ts` — gruppröst
- `backend/app/services/expert_turn_prefetch.py` — parallell minnessökning (textchatten)

Dokumentation:

- [live-voice-workspace-chat.md](../guides/live-voice-workspace-chat.md)
- [live-voice-workspace-chat.md](live-voice-workspace-chat.md) (beslut och protokoll)
- [vad-improvements-investigation.md](vad-improvements-investigation.md)
- [live-speech-provider-verification.md](../guides/live-speech-provider-verification.md)
- [tts-cache.md](../guides/tts-cache.md), [tts-word-cache.md](../guides/tts-word-cache.md)
- [expert-reasoning-route.md](../guides/expert-reasoning-route.md)
- [expert-chat-reasoning-episode.md](expert-chat-reasoning-episode.md)

## 9. Implementerat 2026-10-18 (efter inventeringen)

Följande är genomfört och täckt av tester:

1. **Generation-id på ljudsegment.** `SpeechResponseCoordinator` sätter
   `response_id` + `generation_id` på `audio.output.start` och
   `audio.output.end`. Ett nytt svar eller en ny aside får en ny generation.
   Klienten öppnar ljudmottagning först vid en start, stänger den vid
   `audio.output.end`, och släpper äldre generationer. Lokalt avbruten
   generation förblir blockerad tills en nyare start kommer.
   (`backend/app/services/live_speech_coordinator.py`,
   `frontend/src/products/sme/useLiveSpeechConversation.ts`.)
2. **Lokal nödstopp.** Ett urgent partial (`stopp`, `nej`, `vänta`, `stop`,
   `wait`, `no`) tömmer ljudkön och skickar `turn.cancel` direkt, utan att
   vänta på serverns klassificering. Öppningsrepliken kan tystas på samma
   sätt (`frontend/src/products/sme/liveSpeechBarge.ts`).
3. **Inkrementellt första ljud i verktygsläget.** En rösttur läser upp
   bekräftelserepliken från verktygsvalsanropet innan verktygsepilogen körs, så
   första ljudet inte väntar på hela episoden. Textchatten påverkas inte
   (`backend/app/llm/chat.py`, `backend/app/services/live_speech_progress.py`).

Tester: `backend/tests/test_live_speech_conversation.py` (generation-id,
lead-in) och `frontend/src/products/sme/{liveSpeechBarge,useLiveSpeechConversation}.test.ts`.
Vid verifieringen: 67 backend-tester, 12 frontend-tester, ruff,
maintainability-check och frontend build gröna.

4. **Conversation Controller.** `app/services/conversation_controller.py` äger
   turtagningen med de sju tillstånden (§3) och projicerar till UI-tillståndet;
   `session.state` bär nu `conversation_state`. Tester:
   `tests/test_conversation_controller.py`.
5. **Mätning.** `app/services/latency_stats.py` samlar p50/p95/p99 per fas;
   runtimen emitterar `session.metrics` vid stängning och klienten skickar
   `client.latency` för `vad_reaction`/`stop_playback`. Tester:
   `tests/test_latency_stats.py`. Själva siffrorna kräver ett riktigt samtal
   (se [live-voice-workspace-chat.md](../guides/live-voice-workspace-chat.md)).
6. **Enade leverans- och ljudkomponenter.** Delad `WorkspaceToolDelivery`
   (text/1:1-röst/gruppröst) och delad mik-/VAD-pipeline (`voiceCapture.ts`,
   `speechVadPipeline.ts`).
7. **Strömmande TTS i verktygsläget.** `app/llm/stream_tools.py`
   (`stream_with_tools`) + `app/services/expert_episode_stream.py`
   (`stream_expert_episode`) + `app/services/expert_tool_stream.py`
   (`stream_tool_episode`) strömmar verktygsepilogen token-för-token i
   röstturen, så första innehållsljudet inte väntar på hela episoden.
   Textchatten behåller den icke-strömmande vägen.
8. **Spekulativ läsning.** `app/services/live_speech_speculation.py`
   (`SpeculativeReader`) prefetchar läs-only-verktygen (`find_documents`,
   `search_knowledge`) på stabila partials, cancellar vid nyare partial och
   återanvänds via `app/services/speculative_results.py` när finalfrågan
   matchar. Config: `LIVE_SPEECH_SPECULATION_ENABLED` (default av),
   `LIVE_SPEECH_SPECULATION_MIN_CHARS`. Tester:
   `tests/test_live_speech_speculation.py`.

9. **Fas 2-grund (överlappning/amend).** Barge-in klassificerar nu mjuka
   korrigeringar (`men…`, `fast…`, `alltså…`, `förresten…`, `eller…`,
   `jag menar…`, `det vill säga…`) som `amend` och avbryter med reason
   `amend` i stället för hårt `interruption`. `amend` stoppar uppspelningen
   men **fortsätter samma tur**: `app/services/turn_amendment.py` + 
   `app/services/live_speech_amend.py` stoppar ljudet, lägger tillägget i en
   kanal som den strömmande verktygsepilogen tömmer mellan rundorna
   (`app/services/expert_episode_stream.py`), så modellen reviderar svaret med
   hela kontexten kvar. `ConversationController` spårar `OVERLAPPING` och
   `AI_INTERRUPTED` (sänds i `conversation_state`). Tester:
   `tests/test_live_speech_amend.py`, `tests/test_expert_tool_stream.py`,
   `tests/test_live_speech_conversation.py`, `tests/test_sme_group_voice_barge.py`.

10. **Presentationskontrakt (kanalparitet).** `find_documents`,
    `get_workspace_context`, `show_document` och `show_document_set` ligger
    alltid i modellens verktygslista, och presentationsanrop levereras alltid;
    modellen + verktygsbeskrivningen styr när något öppnas. Den
    deterministiska `IntentDecision.presentation`-spärren
    (`presentation_tools_allowed`, `filter_specs_for_intent`, `allows_gallery`,
    `_drop_find_after_lookup`) är borttagen. Se
    [channel-parity-step-b.md](channel-parity-step-b.md) →
    "Presentation gate removal".

Kvarstår: att mäta p50/p95/p99 på riktigt samtal, samt full Fas 2 — token-nivå
omplanering mitt i en enskild LLM-ström (amend gäller nu mellan verktygsrundor,
inte inne i en call-fri ström) och samtidig uppspelning med flera experter.
Serverns öppnings-aside fortsätter syntetiseras när klienten tystar den; den
spelas inte upp men kostar ett TTS-anrop.
