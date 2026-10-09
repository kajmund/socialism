# Goal

Utöka expertchattens Jev-baserade modellrouting så att valet mellan Snabb, Balanserad och Djup inte enbart baseras på hur intellektuellt svår användarens fråga är.

Routing ska också ta hänsyn till exekveringskomplexitet: hur många steg som krävs, om flera tool calls behöver planeras, om resultat från ett tool avgör nästa steg, om en mängd objekt måste behandlas, om modellen behöver hålla reda på vilka delar som redan behandlats, och om uppgiften kräver fortsatt arbete tills ett completion condition är uppfyllt.

En uppgift kan därför kräva Djup även om varje enskilt steg är enkelt.

Den här specen kompletterar [modellrouting-guiden](../guides/expert-reasoning-route.md) och [dokumentnavigeringsspecen](expert-chat-document-navigation.md). Den inför inga nya logiska profiler och ingen parallell tool retrieval. Parallella workers åt Djup kommer efteråt, i [worker-delegationsspecen](expert-chat-worker-delegation.md).

# Grundprincip

Reasoning complexity består av minst två separata dimensioner:

```text
Cognitive complexity
Execution complexity
```

## Cognitive complexity

Hur mycket analys, syntes, jämförelse och inferens kräver själva problemet?

## Execution complexity

Hur mycket planering, tool orchestration, state tracking och completion tracking krävs för att faktiskt genomföra användarens begäran?

Båda ska påverka modellvalet.

# Exempel

## Kognitivt och exekveringsmässigt enkelt

User:

> Gå till sida 12.

```text
cognitive complexity = LOW
execution complexity = LOW
```

→ Snabb

## Viss kognitiv komplexitet, enkel exekvering

User:

> Vad betyder den här klausulen?

```text
cognitive complexity = MEDIUM
execution complexity = LOW
```

→ Balanserad

## Begränsad kognitiv komplexitet, hög exekveringskomplexitet

User:

> Markera alla klausuler som innehåller hänvisningar till uppsägning.

Varje enskild bedömning är relativt enkel. Uppgiften kräver ändå:

```text
identifiera scope
→ hitta samtliga kandidater
→ kontrollera kandidaterna
→ hålla reda på result set
→ markera samtliga
→ verifiera completion
```

→ Djup

## Hög kognitiv och exekveringsmässig komplexitet

User:

> Markera alla klausuler som du tycker är märkliga och förklara varför.

Det kräver både bedömning av varje relevant klausul, analys av vad som är avvikande, hantering av hela dokumentets scope, result set, flera tool calls, markering och completion tracking.

→ Djup

# Jev-signaler

Utöver befintliga signaler i `chat.expert.reasoning_assessment`:

```text
simple_operation
analysis
multi_step
comparison
synthesis
conflicting_information
```

ska samma frågeschema även omfatta:

```text
tool_orchestration
set_operation
completion_tracking
dependent_steps
```

Frågetexterna ligger i promptfältet, inte som hårdkodade strängar i Python. Reglerna som mappar scores till profil ligger kvar i `app/services/expert_reasoning.py` och ska vara deterministiska. Trösklarna ligger i settings-modulen (`EXPERT_REASONING_*`), inte som utspridda konstanter.

`multi_step` finns redan och fångar att uppgiften har flera steg. De nya signalerna ska inte duplicera den. De ska skilja ut varför stegen är svåra att genomföra: samordning av verktyg, mängd, bokföring av färdigt arbete, och beroende av tidigare resultat.

## tool_orchestration

Bedöm: kräver uppgiften att flera verktygsoperationer planeras eller kombineras för att uppfylla användarens intention?

> Hitta alla ovanliga klausuler och markera dem.

Hög score.

> Gå till sida 12.

Låg score.

## set_operation

Bedöm: gäller användarens begäran en mängd objekt som måste behandlas som en helhet?

Signaler kan vara uttryck som alla, samtliga, varje, de relevanta, samtliga klausuler, alla träffar, alla risker, alla avvikelser och alla hänvisningar. Bedömningen ska vara semantisk och inte en ren keyword-matchning.

> Hitta riskerna i avtalet.

kan innebära en mängdoperation även utan ordet "alla".

## completion_tracking

Bedöm: måste modellen hålla reda på utfört och återstående arbete för att veta när användarens begäran faktiskt är färdig?

> Gå igenom avtalet och markera allt som avviker från standardvillkoren.

Modellen behöver veta vilka delar som analyserats, vilka som återstår, vilka som valts, vilka som markerats och om hela scope är behandlat.

Hög score.

## dependent_steps

Bedöm: är nästa operation beroende av resultatet från en tidigare operation?

```text
find clauses
→ inspect clauses
→ decide which are unusual
→ highlight selected clauses
```

Nästa steg kan inte bestämmas fullständigt innan föregående resultat finns.

Hög score.

# Exempel på Jev assessment

User:

> Markera alla klausuler som du tycker är märkliga.

Jev kan exempelvis ge:

```json
{
  "simple_operation": 0.04,
  "analysis": 0.84,
  "multi_step": 0.96,
  "comparison": 0.22,
  "synthesis": 0.67,
  "conflicting_information": 0.09,
  "tool_orchestration": 0.98,
  "set_operation": 0.97,
  "completion_tracking": 0.94,
  "dependent_steps": 0.91
}
```

Routing: Djup.

# Routingregel

Djup ska väljas när antingen kognitiv komplexitet eller exekveringskomplexitet tydligt kräver det.

```text
if high_cognitive_complexity:
    DJUP
else if high_execution_complexity:
    DJUP
else if clearly_simple:
    SNABB
else:
    BALANSERAD
```

Djup är alltså inte synonymt med en svår fråga. Det är en uppgift som behöver en modell med utrymme att resonera och/eller arbeta agentiskt över flera steg.

Kognitiv Djup-väg är den som redan finns: motstridig information, syntes, jämförelse, eller analys tillsammans med `multi_step`, mot de befintliga trösklarna.

Exekveringsvägen till Djup är ny. Den ska kunna slå till när `tool_orchestration`, `set_operation` och `completion_tracking` tillsammans är höga, även om `analysis` är låg. `dependent_steps` förstärker den bedömningen. En ensam hög score på en exekveringssignal ska inte räcka för att en enkel verktygsoperation, till exempel "markera den här klausulen", blir Djup. Den vägen ska fortfarande kunna bli Snabb via `simple_operation`.

Om kognitiva och exekveringsmässiga signaler pekar åt olika håll och `simple_operation` samtidigt är hög ska profilen inte gissas till Djup. Befintlig ambiguous-regel, som då väljer Balanserad, gäller tills trösklarna kalibrerats mot verkliga turer.

De faktiska trösklarna ska vara centralt konfigurerbara, på samma sätt som dagens `EXPERT_REASONING_DEEP_*` och `EXPERT_REASONING_FAST_*`.

Vid timeout, providerfel eller ogiltigt Jev-svar gäller fortfarande modellrouting-guiden: Balanserad, utan byte av provider eller modell.

# Reasoning episode

När Djup valts ska modellen få äga uppgiften under en sammanhängande reasoning-episod.

```text
User
  ↓
Jev reasoning routing
  ↓
Jev tool retrieval
  ↓
DJUP + relevant tool set
  ↓
┌──────────────────────────────┐
│ reasoning                    │
│   ↓                          │
│ tool call                    │
│   ↓                          │
│ tool result                  │
│   ↓                          │
│ reasoning                    │
│   ↓                          │
│ tool call                    │
│   ↓                          │
│ tool result                  │
│   ↓                          │
│ completion evaluation        │
└──────────────────────────────┘
  ↓
Final answer
```

Modellen ska kunna använda verktyg under sitt resonemang. Tool-anropen sker i samma episod, med samma profil och samma initiala tool set.

Arbetslistan är samma meddelandelista genom serververktyg och genom pausen för klientverktyg. Ett verktygsresultat läggs in som `role: tool` med samma `tool_call_id`. Nästa modellanet fortsätter den listan. Det ersätter ett nytt anrop byggt av den synliga chattexten.

När providern är DeepSeek och anropet har verktyg ska varje tidigare `reasoning_content` skickas tillbaka, annars svarar API:t 400. Fältet sparas på assistentraden och återspelas i nästa tool-anrop. Det ingår inte i svaret till klienten. Cerebras får listan utan fältet, via den befintliga provider-normaliseringen. Ett misslyckat verktygsanrop läggs in som resultat och episoden fortsätter.

# Jev ska inte ligga mellan varje tool call

Undvik detta som normal execution model:

```text
Deep
→ tool
→ Jev
→ Deep
→ tool
→ Jev
→ Deep
```

Det skapar onödig latens, fragmenterad planering, risk att verktyg försvinner mitt under arbetet, och svårare completion tracking.

Jev ska primärt välja en relevant arbetsbänk åt reasoning-modellen.

Befintlig ombedömning i tool-uppföljningen, som kan höja profilen efter ett verktygsresultat men aldrig sänka den, ska inte vara loopen inuti en Djup-episod. Den får fortfarande höja Snabb eller Balanserad till Djup när ett verktygsresultat visar att uppgiften var en mängdoperation som den första bedömningen underskattade. När Djup väl äger episoden körs inte en ny reasoning-bedömning efter varje tool call.

# Tool set per reasoning episode

Jev tool retrieval, enligt dokumentnavigeringsspecen, ska före reasoning-episoden exponera ett tillräckligt tool set för den förväntade uppgiften. Namnen nedan är samma illustrativa capability-etiketter som i den specen. Fas 0 där avgör vilka befintliga verktyg de motsvarar.

User:

> Markera alla klausuler som du tycker är märkliga.

Tool retrieval kan ge:

```text
get_document_outline    .93
find_in_document        .88
read_section            .91
read_around_location    .73
highlight_locations     .96
highlight_location      .42
```

Djup får dessa tools och deras relevance scores. Modellen avgör själv vilka som behövs, i vilken ordning, hur många gånger de används, och när uppgiften är färdig.

# Jev-score är inte exekveringsordning

En högre Jev-score betyder inte att verktyget ska anropas först.

```text
highlight_locations     .97
get_document_outline    .83
read_section            .79
```

Modellen kan korrekt välja:

```text
get_document_outline
→ read_section(...)
→ reasoning
→ highlight_locations(...)
```

trots att `highlight_locations` hade högst relevance score.

Score betyder hur relevant verktyget är för hela användarens intention, inte när verktyget ska köras. Det är samma semantik som dokumentnavigeringsspecens `jev_relevance`: rådgivande ranking, inte bindande tool choice och inte en instruktion om ordning.

# Tool-set expansion

Det kan inträffa att modellen under reasoning upptäcker att en capability saknas från det initiala tool setet. Det ska stödjas utan att hela reasoning-episoden kastas bort.

Inför en intern mekanism, till exempel `request_tool_expansion`. Den är inte ett användarsynligt verktyg och inte ett nytt retrieval-system. Den anropar dokumentnavigeringsspecens befintliga Jev tool retrieval mot det saknade behovet och aktuellt läge, och lägger till de schemas som den retrievaln exponerar.

```text
Deep reasoning
   ↓
required capability unavailable
   ↓
Jev retrieval against missing need/current state
   ↓
additional tool schemas
   ↓
continue same reasoning episode
```

Tool expansion ska vara undantag, inte normalfallet. Den ska inte köras efter varje tool call. Profilen förblir Djup. Redan exponerade verktyg tas inte bort för att en expansion lade till fler.

# Uppgiften, inte tool callet, är completion unit

Ett lyckat tool call betyder inte att användarens uppgift är färdig.

User:

> Markera alla märkliga klausuler.

Efter `highlight_location` på en enskild klausul är modellen inte färdig. Den ursprungliga intentionen är fortfarande alla ovanliga klausuler. Modellen ska fortsätta tills hela uppgiften är uppfylld.

# Completion condition

För agentiska uppgifter ska modellen implicit eller explicit hålla reda på:

```text
original_intent
scope
identified_items
processed_items
remaining_items
completed_actions
```

Final answer får lämnas först när `user_intent_satisfied`, eller när arbetet inte kan fortsätta utan användarens input.

Result set behöver inte persisteras permanent. Det ska däremot kunna finnas kvar i episoden tillräckligt länge för att slutföra den aktuella uppgiften. För en mängdoperation kan det se ut så här:

```text
candidate clauses
    ↓
analysis
    ↓
selected clauses
[
  4.2,
  7.1,
  9.4,
  13.2
]
    ↓
highlight_locations
```

# Ingen onödig mellanbekräftelse

Modellen ska inte fråga "Vill du att jag fortsätter?" mellan steg som redan omfattas av användarens ursprungliga instruktion.

User:

> Markera alla märkliga klausuler.

Otillåtet normalt beteende:

```text
analyze clause 1
→ highlight
→ "Vill du att jag fortsätter?"
```

Användaren har redan begärt hela operationen. Fortsätt tills completion condition är uppfyllt.

# När modellen ska fråga användaren

Fråga endast när det finns verklig blockerande tvetydighet eller ett beslut som användaren behöver fatta.

> Jämför avtalet med @Ramavtal.

är tillräckligt. Fråga inte om lov för varje steg.

> Jämför det med det andra avtalet.

när fem dokument är möjliga och inget kan resolvas säkert: fråga vilket dokument användaren menar.

# Batch operations

Tools som naturligt opererar på en mängd ska stödja batch när det är praktiskt. Vilka capabilities som finns, och om singular- och batchvariant är samma befintliga verktyg eller en utökning, avgörs av dokumentnavigeringsspecen. Den här specen kräver bara agentbeteendet.

```text
highlight_locations([
    location_1,
    location_2,
    location_3,
    location_4
])
```

ska föredras framför fyra separata UI-anrop när hela mängden redan är identifierad. Det gäller särskilt markeringar, relationer, result sets och andra UI-operationer där samma action appliceras på flera identifierade objekt.

Batch är en optimering, inte ett krav för korrekt agentbeteende. Om endast singularverktyget finns ska agenten ändå slutföra uppgiften:

```text
highlight_location(A)
highlight_location(B)
highlight_location(C)
highlight_location(D)
```

är korrekt om `highlight_locations` saknas. Agenten får inte använda avsaknad av batch-tool som anledning att behandla endast första objektet.

# Singular vs batch i Jev tool retrieval

När både singular- och batchvariant finns ska Jev bedöma dem separat, med dokumentnavigeringsspecens retrieval. Bedömningen följer semantisk intention, inte hårdkodad keyword-routing.

User:

> Markera klausul 7.2.

```text
highlight_location       .98
highlight_locations      .31
```

User:

> Markera alla märkliga klausuler.

```text
highlight_locations      .97
highlight_location       .35
```

# Exempel: markera märkliga klausuler

User:

> Markera alla klausuler som du tycker är märkliga.

Jev reasoning assessment:

```text
analysis              HIGH
multi_step            HIGH
tool_orchestration    HIGH
set_operation         HIGH
completion_tracking   HIGH
dependent_steps       HIGH
```

→ Djup

Tool retrieval:

```text
get_document_outline   .92
read_section           .90
find_in_document       .78
highlight_locations    .96
```

Djup kan:

```text
1. identifiera dokumentets klausuler
2. läsa relevant scope
3. bedöma klausulerna
4. skapa result set
5. markera hela result set
6. verifiera att markeringen lyckades
7. svara användaren
```

Ingen mellanfråga behövs.

# Exempel: markera alla uppsägningshänvisningar

User:

> Markera alla hänvisningar till uppsägning.

Detta kräver sannolikt mindre expertanalys men fortfarande betydande execution complexity.

```text
analysis              .31
multi_step            .84
tool_orchestration    .91
set_operation         .98
completion_tracking   .89
dependent_steps       .72
```

Trots relativt låg `analysis` kan resultatet bli Djup, eftersom exekveringskomplexiteten är hög.

# Exempel: enkel markering

User:

> Markera den här klausulen.

```text
simple_operation      .99
analysis              .02
multi_step            .03
tool_orchestration    .04
set_operation         .01
completion_tracking   .02
```

→ Snabb

Ett enstaka tool call är inte skäl att välja Djup.

# Relation till dokumentnavigeringsspecen

Dokumentnavigeringsspecen ansvarar för vilka dokumentcapabilities som finns, återanvändning av befintlig funktionalitet, Jev tool retrieval, tool relevance scores, tool schema exposure och singular/batch capabilities.

Den här specen ansvarar för när uppgiften kräver Djup, agentiskt multi-step reasoning, tool calls under reasoning, completion tracking, mängdoperationer som agentbeteende, och fortsatt execution tills användarens intention är uppfylld.

Dokumentnavigeringsspecens re-routing efter tool call gäller när nästa relevanta operation faktiskt har förändrats och ingen Djup-episod redan äger en arbetsbänk. Inuti en Djup-episod är ny retrieval tool expansion, alltså undantaget ovan, inte ett nytt anrop efter varje resultat.

Implementera inte parallella mekanismer mellan dessa två lager. Expansion anropar samma retrieval. Scores har samma semantik.

# Relation till worker-delegationsspecen

Worker-delegationsspecen ansvarar för när en redan vald Djup-episod får delegera undersökning till tillfälliga workers, och för att huvudagenten fortfarande äger syntes, användarsvar och sidoeffekter.

`decomposable` och `parallelizable` ändrar inte routingregeln i den här specen. De är en grind för `spawn_workers`, inte en fjärde profil. Inför inte `spawn_workers` förrän den här specens acceptance är uppfylld.

# Relation till befintlig modellrouting

Återanvänd befintliga logiska profiler: Snabb, Balanserad, Djup. Skapa inga nya profiler.

Utöka endast Jev-bedömningen och routingreglerna med execution-complexity-signalerna. Provider, modell och reasoning-inställningar kommer fortsatt från `llm_configurations` via befintlig `selection_role`. En profil som ska kunna väljas måste ha `enabled_for_auto=true`, som i modellrouting-guiden.

# Observability

Logga för varje tur, i befintligt `expert_chat.reasoning_routed` under `socialism.expert_chat`, utökat så att det också bär exekveringssignalerna. Själva användarmeddelandet loggas inte.

```text
Jev cognitive scores
Jev execution scores
initial reasoning profile
tool set exposed
tool relevance scores
tool calls
tool results
tool expansions
completion state
final reasoning profile
turn latency
```

För Djup bör det gå att se exempelvis:

```text
routing_reason:
  tool_orchestration=.96
  set_operation=.97
  completion_tracking=.94

profile=deep

tools_used:
  get_document_outline
  read_section x 12
  highlight_locations

completion:
  candidates=12
  selected=4
  highlighted=4
  satisfied=true
```

Tool relevance och vilket verktyg modellen faktiskt valde loggas redan av dokumentnavigeringens retrieval. Den här specen lägger till exekveringsscores, expansionsanrop och completion state. Duplicera inte retrieval-loggen.

Kalibrera trösklar först efter att verkliga expertchattar visar när Djup ger värde: profilfördelning, latens, hur ofta en kognitivt enkel mängdoperation hamnar på Balanserad, och hur ofta en enkel markering hamnar på Djup.

# Failure handling

Ett enskilt misslyckat tool call ska inte automatiskt avsluta reasoning-episoden. Modellen ska kunna förstå felet, försöka igen när det är lämpligt, välja ett annat exponerat tool, begära tool expansion, eller förklara vad som blockerar completion.

Den får inte rapportera en mängdoperation som färdig om endast delar lyckades.

```text
selected=7
highlighted=5
failed=2
```

ska inte rapporteras som "Jag har markerat alla."

Jev-fel vid den inledande routingbedömningen hanteras som i modellrouting-guiden: Balanserad, och felet syns i routing-eventet. Det är inte en alternativ modellväg. Jev-fel vid tool retrieval hanteras som i dokumentnavigeringsspecen och byter inte profil.

# Acceptance criteria

1. Modellrouting tar hänsyn till både cognitive complexity och execution complexity.
2. Jev bedömer `tool_orchestration`, `set_operation`, `completion_tracking` och `dependent_steps` utöver befintliga signaler, via `chat.expert.reasoning_assessment`.
3. En kognitivt enkel men exekveringsmässigt komplex uppgift kan routas till Djup.
4. En enstaka enkel verktygsoperation kan fortfarande routas till Snabb.
5. Djup kan göra flera tool calls under samma reasoning-episod.
6. Jev reasoning-bedömning körs normalt inte mellan varje tool call i en Djup-episod.
7. Det initiala tool setet behålls under reasoning-episoden.
8. Jev relevance score styr hur relevant ett verktyg är för hela intentionen, inte i vilken ordning det ska anropas.
9. Modellen väljer själv vilka exponerade verktyg som används, i vilken ordning och hur många gånger.
10. Tool expansion kan tillföra saknade capabilities i samma episod och är undantag, inte normalfallet.
11. Expansion återanvänder dokumentnavigeringens tool retrieval. Ingen parallell retrieval införs.
12. Uppgiften, inte ett enskilt lyckat tool call, är completion unit.
13. Slutsvar lämnas först när användarens intention är uppfylld, eller när arbetet blockeras av att användaren måste välja.
14. Modellen ber inte om lov mellan steg som redan ingår i den ursprungliga instruktionen.
15. När både singular- och batchvariant finns bedömer Jev dem separat efter semantisk intention.
16. När mängden redan är identifierad föredras batch. Saknas batchverktyget slutförs uppgiften ändå med singularanrop.
17. Inga nya profiler skapas. Snabb, Balanserad och Djup återanvänds, och trösklarna är centralt konfigurerbara.
18. Observability omfattar cognitive- och execution-scores, exponerat tool set, anrop, expansioner, completion state och latens.
19. Ett misslyckat tool call avslutar inte episoden. En delvis genomförd mängdoperation rapporteras inte som färdig.
