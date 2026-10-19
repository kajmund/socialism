# SPEC: Socialism Live Speech – Full Duplex v1.0

**Status:** Implementationsspecifikation
**Projekt:** Socialism
**Prioritet:** Hög
**Mål:** Skapa en röstchatt som upplevs som ett naturligt samtal mellan två människor.

## 1. Övergripande mål

Socialisms röstchatt ska gå från traditionell turbaserad kommunikation till **konversationell full duplex**.

Systemet ska kunna lyssna, tala, resonera och använda verktyg samtidigt.

Det ska stödja två nivåer:

**Fas 1 – Upplevd full duplex**

- Kontinuerlig lyssning även när AI:n pratar.
- Naturliga bekräftelser som "mm", "ja" och "precis".
- Användaren kan avbryta AI:n när som helst.
- Korta lyssnarbekräftelser avbryter inte AI:n.
- AI:n kan börja undersöka en fråga innan användaren pratat färdigt.
- Svar kan börja spelas upp innan hela svaret genererats.
- Pågående verktygsanrop behöver inte blockera samtalet.

**Fas 2 – Konversationell full duplex**

- AI:n och användaren kan prata samtidigt.
- AI:n kan anpassa sitt pågående svar till ny information.
- AI:n kan ändra riktning mitt i en mening.
- Flera experter kan delta i samma samtal.
- Experter kan förbereda svar och begära ordet medan andra pratar.

## 2. Grundläggande arkitektur

Befintliga komponenter ska återanvändas.

| Komponent | Ansvar |
|---|---|
| Streaming STT | Kontinuerlig transkribering |
| WebRTC Audio Processing | Ekoreducering och ljudbehandling |
| VAD | Detektera talaktivitet |
| JEV | Klassificering och routing |
| Qwen/OSS | Snabb samtalsmodell |
| DeepSeek/annan LLM | Resonemang och svar |
| ElevenLabs | Strömmande TTS |
| Overgraph | Kunskap och kontext |
| mem0 | Persistent minne |
| Befintlig tool-router | Asynkrona verktygsanrop |

**Viktigt:** Ingen ny parallell verktygsrouter, minnesdatabas eller agentarkitektur får byggas.

### 2.1 Tre oberoende processer

**Listener Pipeline**

Tar kontinuerligt emot mikrofonljud, utför VAD och STT och identifierar användarens samtalsintention.

**Conversation Controller**

Bestämmer vem som har ordet, om AI:n ska fortsätta prata, pausa, bekräfta eller lämna över ordet.

**Response Pipeline**

Genererar innehåll, anropar verktyg och producerar ljud via ElevenLabs.

Processerna ska vara asynkrona och kommunicera genom typade events.

## 3. Conversation Controller

En central tillståndsmaskin ska styra samtalet.

### Tillstånd

```typescript
type ConversationState =
  | "IDLE"
  | "USER_SPEAKING"
  | "USER_PAUSED"
  | "AI_THINKING"
  | "AI_SPEAKING"
  | "OVERLAPPING"
  | "AI_INTERRUPTED";
```

Tillståndsmaskinen ska inte blockera ljudströmmen eller modellernas arbete.

AI:n kan exempelvis befinna sig i `AI_SPEAKING` samtidigt som en resonemangsmodell arbetar och ett verktygsanrop pågår.

Tillståndet beskriver samtalets turfördelning, inte samtliga bakgrundsprocesser.

## 4. Intelligent barge-in

Systemet ska skilja mellan lyssnarbekräftelser och verkliga avbrott.

| Yttrande | Åtgärd |
|---|---|
| "Mm" | Fortsätt |
| "Ja" | Fortsätt |
| "Precis" | Fortsätt |
| "Just det" | Fortsätt |
| "Fast..." | Förbered paus |
| "Vänta lite" | Pausa AI |
| "Stopp" | Stoppa AI omedelbart |
| Ny längre mening | Lämna över ordet |
| Ny fråga | Avbryt och behandla frågan |

Klassificeringen ska kombinera ljudaktivitet, transkription, yttrandets längd och samtalskontext.

**Viktigt:** Ett kort yttrande får inte automatiskt ignoreras. "Nej" kan exempelvis vara ett viktigt avbrott.

Vid tydligt avbrott ska ljuduppspelningen stoppas lokalt utan att invänta LLM eller JEV.

## 5. Incremental Speech Commitment

AI:n ska inte behöva generera hela svaret innan den börjar prata.

Exempel:

```text
LLM:
"Ja, det skulle kunna fungera."
             ↓
         ElevenLabs
             ↓
         Uppspelning

LLM fortsätter:
"Men då behöver vi..."
             ↓
         ElevenLabs
```

### Krav

1. Text delas i naturliga, talbara segment.
2. Segment skickas löpande till ElevenLabs.
3. Ljudsegment spelas upp i korrekt ordning.
4. Nästa segment kan genereras medan föregående spelas.
5. Vid avbrott stoppas uppspelning och väntande segment.
6. Redan genererat innehåll kan återanvändas om det fortfarande är relevant.

Varje segment ska kopplas till ett `response_id` och ett `generation_id`.

Föråldrade segment får aldrig spelas upp efter ett avbrott.

## 6. Spekulativ exekvering

Systemet ska kunna förbereda informationshämtning innan användaren avslutat sin fråga.

Exempel:

**Användare:** "Vilka av våra avtal..."

Systemet identifierar ämnet avtal.

**Användare:** "...löper ut nästa kvartal..."

Systemet kan påbörja sökning i Overgraph.

**Användare:** "...och har automatisk förlängning?"

Systemet kompletterar sökningen.

### Regler

Spekulativ exekvering får endast användas för säkra, läsande operationer.

Skrivningar, mejl, bokningar och andra externa åtgärder kräver en bekräftad användarintention och befintliga behörighetskontroller.

Varje spekulativ operation ska kunna avbrytas eller markeras som inaktuell.

Resultat får återanvändas när den slutliga frågan är förenlig med den preliminära.

## 7. Latensmål

Följande är initiala designmål som ska verifieras genom mätning.

| Händelse | Mål |
|---|---:|
| Lokal VAD-reaktion | < 50 ms |
| Stoppa lokal ljuduppspelning | < 100 ms |
| Identifiera tydligt avbrott | < 200 ms |
| JEV-klassificering | ~120 ms |
| Första naturliga respons | < 500 ms |
| Första innehållsbärande ljud | < 1 000 ms |

Mätning ska göras med p50, p95 och p99.

Systemet får inte använda en långsam modell för beslut som kan fattas direkt i ljudpipen.

## 8. Implementation och migrering

**Innan någon ny kod skrivs ska befintlig implementation inventeras.**

Inventeringen ska identifiera:

- Nuvarande streaming-STT och ljudtransport.
- Befintlig VAD och barge-in.
- Hur ElevenLabs används och hur ljud buffras.
- Befintlig JEV-routing.
- Hur snabba och resonerande modeller samverkar.
- Hur asynkrona verktygsanrop hanteras.
- Hur avbrott och cancellation fungerar idag.

Befintliga komponenter ska byggas ut i stället för att dupliceras.

### Rekommenderad implementationsordning

**Steg 1:** Kontinuerlig mikrofon och ekoreducering under AI-uppspelning.

**Steg 2:** Intelligent barge-in med filtrering av lyssnarbekräftelser.

**Steg 3:** Central Conversation Controller med tydlig tillståndshantering.

**Steg 4:** Strömmande TTS med segmentkö, generations-ID och cancellation.

**Steg 5:** Snabb samtalsmodell parallellt med resonemangsmodellen.

**Steg 6:** Spekulativ läsning och verktygsexekvering.

**Steg 7:** Verklig överlappande dialog och dynamisk omplanering av pågående svar.

## 9. Acceptanskriterier för fas 1

Implementationen är godkänd när följande fungerar:

1. Användaren kan prata medan AI:n pratar.
2. AI:n transkriberar inte sin egen uppspelning som användartal.
3. "Mm", "ja" och "precis" avbryter normalt inte AI:n.
4. "Stopp" avbryter uppspelningen omedelbart.
5. Användaren kan ställa en ny fråga mitt i ett AI-svar.
6. Gamla ljudsegment spelas inte upp efter ett avbrott.
7. Verktygsanrop kan fortsätta i bakgrunden när det är relevant.
8. AI:n kan börja prata innan hela svaret är genererat.
9. Befintlig JEV-routing och verktygsarkitektur återanvänds.
10. Samtalet fungerar även när den djupare resonemangsmodellen tar flera sekunder.

## 10. Viktig arkitekturprincip

**Conversation Controller ska äga turtagningen, inte LLM:en.**

LLM:en producerar innehåll och föreslår samtalshandlingar.

Conversation Controller avgör när dessa får utföras utifrån ljudaktivitet, samtalstillstånd och användarens intention.

Detta gör att vi kan byta mellan Qwen, OSS, DeepSeek och andra modeller utan att behöva bygga om själva samtalslogiken.

---

**Slutmål:** Socialisms röstchatt ska kännas som att prata med en kunnig kollega som lyssnar, tänker och reagerar i realtid – inte som att diktera frågor till en chatbot.

Den viktigaste första leveransen är **kontinuerlig lyssning + intelligent barge-in + strömmande TTS**. Det ger sannolikt den största upplevda förbättringen innan vi bygger verkligt överlappande dialog.
