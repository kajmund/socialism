# Goal

Ge Djup möjlighet att delegera avgränsade deluppgifter till tillfälliga workers när en uppgift är både uppdelbar och parallelliserbar.

Workers undersöker och returnerar struktur. Huvudagenten ansvarar för bedömning över hela mängden, användarinteraktion, completion och varje sidoeffekt.

Underagenter är inte experter, inte personas och inte research-workers. De är tillfälliga workers åt den aktuella experten.

Den här specen kompletterar [resonemangsspecen](expert-chat-reasoning-episode.md) och [dokumentnavigeringsspecen](expert-chat-document-navigation.md). Den inför inga nya logiska profiler och ingen parallell tool retrieval.

# Byggordning

Workers multiplicerar en orchestrator. De ska därför inte införas förrän huvudagenten själv kan genomföra en multi-step-uppgift korrekt.

Ordningen är:

```text
1. Kognitiv och exekveringsrouting via Jev
2. Dokument-tool retrieval och schema-exponering
3. Agentisk completion i en Djup-episod
4. spawn_workers
```

Steg 1–3 beskrivs i resonemangsspecen och dokumentnavigeringsspecen. Den här specen börjar efter att de är uppfyllda.

Implementera inte `spawn_workers` samtidigt som execution-complexity-signalerna eller dokumentverktygen. Om huvudagenten ännu inte kan slutföra en mängduppgift själv multiplicerar workers mest dagens problem.

# Grundprincip

```text
Underagenter får undersöka och returnera resultat.
Huvudagenten ansvarar för beslut, användarinteraktion och completion.
```

Annars uppstår agentkaos där flera workers börjar markera dokument, skapa objekt eller anropa andra agents.

```text
                   DJUP / EXPERT
                        │
              get_document_outline
                        │
           ┌────────────┼────────────┐
           ↓            ↓            ↓
        Worker 1      Worker 2     Worker 3
       § 1–10        § 11–20      § 21–30
           │            │            │
           └────────────┼────────────┘
                        ↓
                 DJUP syntetiserar
                        ↓
             highlight_locations(...)
```

Workers är read-only. Sidoeffekter, till exempel markering, skapande, research och fjärrexpert, stannar hos huvudagenten.

# Jev-signaler

Lägg `decomposable` och `parallelizable` i samma frågeschema som övriga Jev-frågor, `chat.expert.reasoning_assessment`. Frågetexterna ligger i promptfältet, inte som hårdkodade strängar i Python. Trösklarna ligger i settings-modulen (`EXPERT_REASONING_*`).

Signalerna ingår inte i `route_scores`. Profilen förblir Snabb, Balanserad eller Djup enligt resonemangsspecen. De avgör bara om `spawn_workers` exponeras efter att profilen redan är vald.

## decomposable

Bedöm: kan uppgiften delas i avgränsade deluppgifter vars resultat sedan kan vägas ihop?

> Gå igenom avtalet och markera alla klausuler som verkar märkliga.

Hög score. Avtalet kan delas i sektioner som granskas var för sig.

> Jämför klausul 3 med klausul 7.

Låg score. Delarna är inte självständiga; bedömningen är relationen mellan dem.

## parallelizable

Bedöm: kan deluppgifterna utföras samtidigt utan att nästa del beror på föregående dels resultat?

> Granska klausuler 1–10, 11–20 och 21–30 mot samma kriterium.

Hög score.

> Hitta ovanliga klausuler och jämför dem sedan med ramavtalet.

Låg score för parallellisering av hela uppgiften. Identifiering måste ske före jämförelsen. En senare delmängd kan fortfarande vara parallell, men den inledande bedömningen ska inte exponera spawn för hela turen.

`dependent_steps` från resonemangsspecen fångar att nästa operation beror på föregående resultat. `parallelizable` är den omvända egenskapen för de delar som kan delas. De ska inte duplicera varandra.

# Exempel på Jev assessment

User:

> Gå igenom avtalet och markera alla klausuler som verkar märkliga.

Jev kan exempelvis ge:

```json
{
  "simple_operation": 0.03,
  "analysis": 0.91,
  "multi_step": 0.94,
  "comparison": 0.41,
  "synthesis": 0.72,
  "conflicting_information": 0.11,
  "tool_orchestration": 0.96,
  "set_operation": 0.98,
  "completion_tracking": 0.94,
  "dependent_steps": 0.88,
  "decomposable": 0.97,
  "parallelizable": 0.95
}
```

Routing: Djup. `spawn_workers` exponeras.

User:

> Jämför klausul 3 med klausul 7.

```json
{
  "simple_operation": 0.06,
  "analysis": 0.91,
  "multi_step": 0.71,
  "comparison": 0.96,
  "synthesis": 0.44,
  "conflicting_information": 0.08,
  "tool_orchestration": 0.52,
  "set_operation": 0.18,
  "completion_tracking": 0.21,
  "dependent_steps": 0.74,
  "decomposable": 0.32,
  "parallelizable": 0.18
}
```

Routing: Djup. `spawn_workers` exponeras inte.

# Grind för spawn

`spawn_workers` exponeras bara när samtliga villkor är sanna:

```text
profile == deep
decomposable >= EXPERT_REASONING_SPAWN_DECOMPOSABLE
parallelizable >= EXPERT_REASONING_SPAWN_PARALLELIZABLE
```

Snabb och Balanserad får aldrig verktyget. Om mängden kräver workers ska exekveringsvägen i resonemangsspecen redan ha valt Djup.

Jev-fel vid den inledande routingbedömningen följer modellrouting-guiden: Balanserad. Spawn exponeras då inte. Det är inte en alternativ modellväg och inte en tyst degrade till workers.

Verktyget är en del av arbetsbänken, inte ett krav att anropa. Huvudagenten kan fortfarande slutföra uppgiften själv.

```text
User
  ↓
Jev reasoning routing
  ↓
Jev tool retrieval
  ↓
Djup och decomposable och parallelizable?
  ↓ ja
DJUP + relevant tool set + spawn_workers
  ↓
spawn_workers → workers → syntes → sidoeffekter
```

Om grinden är nej får Djup samma arbetsbänk som resonemangsspecen redan beskriver, utan spawn.

# Ägarskap

Workers är tillfälliga undersökare åt den aktuella experten.

De är inte:

- expertpersonas,
- research-workers,
- noder i forsknings-DAG:en,
- en ny användarsynlig agentyta.

Befintlig `research_worker`, question DAG och `execute_attempt_research` återanvänds inte som den här mekanismen. De löser bakgrundsforskning med lease och persistens. Workers här är synkrona delberäkningar inuti en Djup-episod.

Huvudagenten äger:

```text
original_intent
scope
vilka deluppgifter som skapas
vilken worker-profil som används
syntes över hela mängden
användartext
completion
varje sidoeffekt
```

Workers äger endast sin deluppgift och sitt strukturerade returvärde.

# spawn_workers

Ett anrop, en batch. Runtime kör deluppgifterna med `asyncio` under ett tak i settings, så parallelliteten inte beror på att modellen råkar emittera flera tool calls.

```text
spawn_workers(
  worker_profile,          # fast | balanced
  tasks: [{ task, scope, context, allowed_tools, output_schema }]
)
```

`worker_profile` väljs av huvudagenten per batch. Alla tasks i samma anrop delar profil. Djup-workers finns inte i första versionen. En del som behöver Djup stannar hos huvudagenten.

Workers kan inte anropa `spawn_workers` eller `request_tool_expansion`.

Tom `tasks`, fler tasks än taket, okänd `worker_profile` eller saknade fält är ett misslyckat anrop, inte en tyst kapning eller breddning.

## task

Instruktionen till workern. Den ska vara avgränsad och beskriva vad som ska identifieras eller bedömas, inte vad som ska markeras eller skapas.

```text
Granska klausuler 1–10 och identifiera sådana
som avviker från normala kommersiella villkor.
```

## scope

Kända section- eller anchor-id från outline, knutna till ett dokument som redan är resolvat. Läsanrop utanför scopet avvisas.

Scope ska komma från ett tidigare tool-resultat i episoden, till exempel `read_source` outline. Huvudagenten får inte skicka fria sidintervall eller rå text som scope.

## context

Endast den kontext workern behöver för deluppgiften: kriterium, jämförelsenorm, relevanta definitioner. Inte hela chatten och inte huvudagentens övriga tool-resultat.

## allowed_tools

Ett snitt mot en server-side läslista. Förälder kan inte ge bort verktyg utanför listan.

## output_schema

JSON Schema för returvärdet. Runtime validerar svaret. Ogiltigt schema i anropet eller ogiltig JSON från workern är ett misslyckat task-resultat.

Exempel:

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "required": ["anchor_id", "assessment", "reason", "confidence"],
    "properties": {
      "anchor_id": { "type": "string" },
      "assessment": { "type": "string" },
      "reason": { "type": "string" },
      "confidence": { "type": "number" }
    }
  }
}
```

`confidence` krävs inte av runtime om schemat inte ber om det. När schemat ber om det ska värdet valideras som övriga fält.

# Minsta verktygsmängd

Workers ärver inte huvudagentens hela tool set.

Läslistan är dokumentläsning och sökning som dokumentnavigeringsspecen redan namnger:

```text
read_source          outline / section / quote
search_knowledge     semantisk och exact
```

Capability-etiketter som `read_section`, `search_document` och `read_around_location` i exempel är samma inventerade verktyg. Skapa inte parallella worker-verktyg.

Workers får inte:

```text
highlight_location
highlight_locations
focus_anchor
show_document
create_document
start_research
ask_expert
consult
request_tool_expansion
spawn_workers
```

Förälder som listar ett förbjudet verktyg i `allowed_tools` får ett misslyckat anrop, inte en tyst filtrering som låter övriga tasks köra.

Ogiltigt schema, scope utanför dokumentet eller ett verktyg utanför läslistan är ett misslyckat anrop, inte en tyst breddning.

# Worker-runtime

Varje worker:

1. Kort databastransaktion för att läsa sitt utsnitt och materialisera det som behövs.
2. Släpp anslutningen.
3. LLM-anrop och eventuella ytterligare läsverktyg, varje läs med egen kort transaktion.

Ingen anslutning, öppen transaktion eller databaslås får hållas över worker-anropet. Det är samma regel som [AGENTS.md](../../AGENTS.md) redan kräver för varje kodväg som kombinerar databas och externa anrop.

När implementationen kommer ska ett regressionstest med poolstorlek 1 visa att en annan klient kan få en anslutning medan en workers LLM-anrop pågår.

Workers ser inte hela chatten. De ärver expertens identitet bara så att bedömningen är samma experts. Instruktionen är smal: returnera schemat, ingen användartext.

Provider, modell och reasoning-inställningar för `fast` och `balanced` kommer från `llm_configurations` via befintlig `selection_role`, samma som huvudagenten.

# Resultat och fel

Varje worker returnerar validerad JSON enligt `output_schema`. Runtime samlar delresultaten i samma ordning som `tasks`.

Ett worker-fel, timeout eller trasigt JSON blir ett felobjekt för den delen. Övriga delar behålls.

```text
[
  { "ok": true, "result": [ ... ] },
  { "ok": false, "error": "timeout" },
  { "ok": true, "result": [ ... ] }
]
```

Huvudagenten får inte rapportera mängden som klar om någon del saknas eller föll. Samma completion-regel som resonemangsspecen: uppgiften, inte ett enskilt lyckat anrop, är completion unit.

```text
selected=7
worker_ok=5
worker_failed=2
```

ska inte rapporteras som "Jag har gått igenom hela avtalet."

Efter syntes gör huvudagenten sidoeffekten, till exempel en batch-markering, med verktyg som bara den har. Workers markerar inte.

Ett misslyckat `spawn_workers`-anrop avslutar inte reasoning-episoden. Huvudagenten kan dela om, slutföra återstående delar själv, eller förklara vad som blockerar completion.

# Observability

Utöka befintligt `expert_chat.reasoning_routed` under `socialism.expert_chat`. Duplicera inte retrieval-loggen från dokumentnavigeringen.

Lägg till:

```text
decomposable
parallelizable
spawn_exposed
worker_count
worker_profile
allowed_tools
worker_latency_ms
worker_failed_count
```

Själva användarmeddelandet loggas inte.

Ingen ny användarsynlig "agent"-yta och ingen operatorguide förrän något syns för operatören. Modellspåret kan visa anropet som ett tool call med barndelar.

# Relation till resonemangsspecen

Resonemangsspecen ansvarar för när uppgiften kräver Djup, agentiskt multi-step reasoning, completion tracking och fortsatt execution tills användarens intention är uppfylld.

Den här specen ansvarar för när en redan vald Djup-episod får delegera undersökning till workers, och för att huvudagenten fortfarande äger syntes, användarsvar och sidoeffekter.

`decomposable` och `parallelizable` ändrar inte routingregeln. De är en grind för ett verktyg, inte en fjärde profil.

# Relation till dokumentnavigeringsspecen

Dokumentnavigeringsspecen ansvarar för vilka dokumentcapabilities som finns, återanvändning av befintlig funktionalitet, Jev tool retrieval och schema-exponering.

Workers använder samma läsverktyg och samma identiteter. Skapa inte en parallell dokumentväg för workers. `allowed_tools` är ett snitt mot den katalogen, inte en ny katalog.

# Relation till research

Research-workers, question DAG och `start_research` är en annan mekanism. De persisterar arbete, tar lease och körs utanför chatt-turen. `spawn_workers` är synkront inuti episoden och returnerar struktur till huvudagenten. Återanvänd inte research-runtime som worker-runtime.

# Acceptance criteria

1. `decomposable` och `parallelizable` bedöms av Jev via `chat.expert.reasoning_assessment` och ingår inte i `route_scores`.
2. Signalerna ändrar inte profil. Snabb, Balanserad och Djup återanvänds.
3. `spawn_workers` exponeras bara på Djup när båda signalerna ligger över tröskel.
4. En jämförelse av två klausuler kan vara Djup utan att spawn exponeras.
5. Snabb och Balanserad får aldrig spawn. Jev-fel exponerar inte spawn.
6. Workers är tillfälliga undersökare åt den aktuella experten, inte personas och inte research-workers.
7. Workers är read-only, scopade till kända section- eller anchor-id, och kan inte spawna vidare eller begära tool expansion.
8. `allowed_tools` är ett snitt mot server-side läslistan. Förbjudna verktyg gör anropet ogiltigt.
9. Ett anrop är en batch. Runtime kör tasks parallellt under ett tak i settings.
10. Worker-profilen är `fast` eller `balanced`. Djup-workers finns inte i första versionen.
11. Huvudagenten gör syntes, användarsvar och sidoeffekter.
12. Partiellt worker-fel räknas inte som färdig mängd.
13. Ogiltigt schema, scope utanför dokumentet eller verktyg utanför läslistan är ett misslyckat anrop, inte en tyst breddning.
14. Ingen databasanslutning hålls över worker-LLM-anropet. Implementationen ska ha ett regressionstest med poolstorlek 1.
15. Observability utökar `expert_chat.reasoning_routed` med spawn- och workerfält. Ingen ny användarsynlig agentyta införs.
16. Research-workers och expertpersonas återanvänds inte som den här mekanismen.
17. Implementation sker efter att resonemangsspecen och dokumentnavigeringsspecen är uppfyllda.
