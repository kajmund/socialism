# Goal

Expertchatten ska få naturlig dokumentnavigation med små, tydligt avgränsade verktyg.

Jev ska fungera som semantic tool retrieval:

1. bedöma vilka verktyg som är relevanta för användarens aktuella intention,
2. filtrera vilka tool schemas som exponeras för huvud-LLM:en,
3. ranka de exponerade verktygen med Jev relevance scores,
4. låta huvud-LLM:en fatta det slutliga beslutet om vilket eller vilka verktyg som används och i vilken ordning.

Detta ska byggas vidare på befintlig workspace-, dokument-, ingest-, knowledge- och viewerfunktionalitet. Skapa inte en parallell dokumentarkitektur.

Namn som `find_in_document`, `go_to_location` och `highlight_location` i den här specen är illustrativa capability-etiketter. Fas 0 avgör om de redan motsvaras av befintliga verktyg, till exempel `show_document`, `focus_anchor`, `search_knowledge`, `read_source` eller `get_workspace_context`. De är inte en order att skapa ett nytt verktyg per namn.

# Fas 0 – inventera befintlig funktionalitet

**Gör denna inventering innan implementation eller databasändringar påbörjas.**

Gå igenom nuvarande implementation på `main` och identifiera all befintlig funktionalitet som berör:

- workspace state
- aktivt dokument
- synliga/öppna dokument
- aktuell markering/selection
- anchors och dokumentpositioner
- dokumentrevisioner
- dokumentstruktur, sections och headings
- sidnummer och annan positionsmetadata
- `show_document`
- `focus_anchor` / befintlig markering eller fokusering
- `get_workspace_context`
- `search_knowledge`
- `read_source`
- dokument-Q&A och document knowledge
- text units/chunks och deras positionsmetadata
- ingest och dokumentparsing
- `show_comparison`
- befintliga source/document-ID:n
- viewer state
- eventuell navigation history
- frontendens dokumentvisare och dess befintliga API
- befintliga chat/voice tool registry och tool execution
- befintliga Jev-integrationer som kan återanvändas

Utgå från koden på `main` och från den dokumentation som redan beskriver dessa ytor, bland annat [live voice-specen](live-voice-workspace-chat.md), [live voice-guiden](../guides/live-voice-workspace-chat.md), [document knowledge ingest](../guides/document-knowledge-ingest.md) och [text-unit-knowledge](../guides/text-unit-knowledge.md). Inventeringen ska ändå verifieras mot implementationen, inte mot den här specens exempel.

Dokumentera för varje föreslagen capability:

```text
Proposed tool
Existing capability
Reuse / extend / new
Reason
```

Exempel på hur mappningen ska se ut. Namnen till vänster är capability-etiketter, inte beslutade nya verktyg:

```text
highlight_location
→ existing focus_anchor
→ EXTEND/REUSE
→ do not create parallel highlighting mechanism
```

```text
get_document_position
→ workspace selection + active document state
→ REUSE
```

## Viktig regel

Om motsvarande funktionalitet redan finns: **återanvänd eller utöka den.**

Skapa inte:

- ett nytt anchor-system om ett redan finns,
- ett nytt dokument-ID om `source_object_id` eller annan canonical identity redan används,
- separat selection state,
- separat viewer state,
- separat dokumentindex,
- separat dokumentparser,
- separat knowledge representation,
- parallell highlight-mekanism,
- parallell tool execution pipeline.

Ett nytt chattool får gärna vara ett tunt semantiskt lager ovanpå befintlig funktionalitet.

Exempel: om befintlig viewer- eller focus-mekanism redan flyttar vyn till en känd position är det bättre än en ny navigationsmotor. Capabilityn "navigera till location" kan då vara `focus_anchor` eller `show_document` med en tydligare beskrivning och ett schema, inte ett nytt `go_to_location`.

## Rapportera inventeringen först

Innan större implementation påbörjas ska inventeringen sammanfattas.

Om specens föreslagna verktygsgränser inte passar den befintliga arkitekturen ska implementationen anpassas efter den befintliga arkitekturen i stället för att duplicera den.

## Inventeringsresultat

Capability-etiketterna är mappade på befintliga verktyg. Inga parallella verktygsnamn har införts.

```text
dokumentposition
→ get_workspace_context + workspace state (documents, selection, page) + document_mentions
→ REUSE

dokumentstruktur
→ document_sections och text units från ingest, lästa via read_source outline/section
→ EXTEND read_source

semantisk sökning
→ search_knowledge
→ REUSE

exakt textsökning
→ befintliga text units och extracted_text via search_knowledge exact=true
→ EXTEND search_knowledge
→ inget andra dokumentindex

navigera till sida
→ show_document page
→ REUSE

navigera till location och markera passage
→ focus_anchor
→ REUSE
→ samma klientoperation flyttar vyn och markerar; ingen parallell highlight

läs runt en position och läs sektion
→ text units via read_source quote/section
→ EXTEND read_source

följ dokumentintern referens
→ read_source section mot befintliga section-titlar, därefter show_document och focus_anchor
→ EXTEND read_source

byta dokument
→ show_document source_id
→ REUSE

@document
→ klienten matchar @filnamn exakt mot kända filer och skickar source_object_id i document_mentions
→ EXTEND
→ tool-lagret fuzzy-matchar inte filnamnet efter resolve

nästa/föregående träff och navigation history
→ ingen befintlig sökcursor eller viewer-historik
→ inte infört
→ skulle vara ny viewer state

Jev-rankning och exponering
→ befintlig HttpJevSystemOne ovanpå den befintliga workspace-toolkatalogen
→ EXTEND
→ Jev-fel återgår till den omarkerade katalogen
```

# Grundprincip för dokumentverktygen

Dokumentverktygen ska vara små och semantiskt tydliga.

Undvik ett generellt `document_navigation(action=...)` med många actions om befintlig arkitektur inte uttryckligen motiverar det.

Föredra logiska capabilities såsom: hitta, läsa, navigera, markera, följa referens, läsa struktur.

De konkreta tool-namnen ska fastställas **efter Fas 0**, så att befintliga verktyg kan återanvändas. Flera capabilities kan dela ett befintligt verktyg om dess schema och beskrivning redan skiljer användningarna åt tillräckligt för Jev. Skapa inte ett andra lager med samma effekt.

# Önskade capabilities

Följande är capabilities som ska finnas efter implementationen. De är inte ett krav på att skapa ett nytt tool för varje rad. Tool-namn i exemplen nedan är illustrativa capability-etiketter tills Fas 0 har mappat dem.

## Dokumentposition

Chatten ska kunna få reda på: aktivt dokument, aktuell sida/position, aktuell anchor/section, användarens selection. Återanvänd befintlig workspace state där möjligt.

## Dokumentstruktur

Chatten ska kunna läsa en navigerbar outline: rubriker, sections, klausuler, befintliga bookmarks/anchors. Använd information som redan produceras vid ingest innan ny strukturdetektion införs.

## Semantisk sökning i ett dokument

"Var står det om förtida uppsägning?" ska ge kandidater med stabil dokumentposition. Återanvänd text units, embeddings, document knowledge och befintliga sökfunktioner. Skapa inte ett andra dokumentindex enbart för navigation utan tydligt behov.

## Exakt textsökning

Hitta en känd textsträng deterministiskt. Semantisk sökning ska inte användas när exakt text och exakt position kan hittas billigare och säkrare.

## Navigera till sida

"Gå till sida 17."

## Navigera till location/anchor

När en position redan är identifierad ska chatten kunna flytta dokumentvyn dit utan ny sökning.

## Navigera till section

"Visa klausul 12.4." Använd befintlig dokumentstruktur när destinationen kan identifieras deterministiskt.

## Nästa/föregående

Nästa/föregående search match och nästa/föregående section, om detta passar befintlig viewer state.

## Läs runt en position

Kontext runt en träff (till exempel 2 stycken före, match, 2 stycken efter). Återanvänd text units och befintlig källäsning.

## Läs hela sektionen

När dokumentstrukturen är känd ska hela den relevanta klausulen eller sektionen kunna läsas.

## Markera passage

Återanvänd befintlig `focus_anchor`- eller viewer-funktionalitet om den redan löser detta. LLM:en får bara säga att något markerats eller visats efter bekräftad klientoperation.

## Följ dokumentintern referens

"se punkt 12.4" ska kunna resolvas till dokumentets befintliga section eller anchor och därefter visas.

## Navigation history

"gå tillbaka" och "gå framåt" om detta kan byggas naturligt ovanpå befintlig viewer- eller navigationsstate.

## Byta dokument

Navigera mellan identifierade dokument. Explicit `@document` ska använda canonical document identity och inte fuzzy-matchas från filnamnet efter att mentionen har resolverats.

# @document

En explicit document mention ska resolvas i klienten till canonical ID.

Konceptuellt:

```json
{
  "display_name": "Ramavtal.pdf",
  "source_object_id": "abc-123"
}
```

Tool-lagret ska använda ID:t. Om Fas 0 visar att en annan befintlig identitet redan är kanonisk ska den användas i stället för att införa ett nytt dokument-ID. `source_object_id` är utgångspunkten när den redan är kanonisk.

Exempel:

- "Visa uppsägningsklausulen i @Ramavtal.pdf."
- "Jämför den här klausulen med motsvarande klausul i @Ramavtal.pdf."
- "Öppna @Ramavtal.pdf och gå till punkt 12."

Aktivt dokument och aktuell selection ska samtidigt kunna användas för "det här dokumentet", "den här klausulen" och "det här stycket".

# Jev tool retrieval

LLM:en ska inte alltid få hela tool-katalogen.

Efter deterministisk capability- och state-filtrering ska Jev bedöma: hur relevant är detta verktyg för att uppfylla användarens aktuella intention?

Exempel på scores. Namnen är illustrativa capability-etiketter i väntan på Fas 0-mappning:

```text
find_in_document       0.97
highlight_location     0.91
go_to_location         0.86
read_around_location   0.72
go_to_page             0.06
clear_highlights       0.01
```

Jev fungerar här som retrieval och ranking, inte som agent. Jev väljer inte verktyg och kör inte nästa steg.

# Två användningar av Jev-score

1. Avgöra vilka schemas som exponeras. Irrelevanta verktyg ska normalt inte skickas till huvud-LLM:en.
2. Inbördes ranking. De verktyg som exponeras ska behålla sina scores. Högst score presenteras först.

Konceptuellt promptformat. Namn och texter är illustrativa tills Fas 0 har fastställt de verkliga verktygen:

```text
Verktyg rankade efter semantisk relevans för den aktuella intentionen.
jev_relevance är rådgivande för vilket verktyg som ska användas, inte för om
ett uppslag ska ske. Den är inte en sannolikhet att anropet lyckas och inte
confidence för verktygsresultatet. En fråga som kräver uppslag ska anropa
minst ett verktyg.

1. find_in_document
   jev_relevance: 0.97
   <en semantiskt distinkt beskrivning>

2. highlight_location
   jev_relevance: 0.91
   <en semantiskt distinkt beskrivning>

3. go_to_location
   jev_relevance: 0.86
   <en semantiskt distinkt beskrivning>
```

# Score-semantik

LLM:en ska instrueras att `jev_relevance` anger hur starkt verktygets syfte semantiskt matchar den aktuella intentionen.

Det är inte:

- sannolikheten att tool-anropet lyckas,
- confidence för tool-resultatet,
- ett krav att använda verktyget.

LLM:en får välja det högst rankade verktyget, välja ett lägre rankat, använda flera, eller avstå från tool call.

# State filtering före Jev

Verktyg som deterministiskt inte kan användas ska tas bort innan Jev körs.

Exempel, med illustrativa capability-etiketter:

- nästa träff är irrelevant utan aktiv sökning,
- gå framåt är irrelevant utan forward history,
- dokumentberoende verktyg kräver ett dokument,
- selection-baserade operationer kräver selection eller en möjlighet att identifiera en position.

Flöde:

```text
Full tool registry
  → Capability/state filtering
  → Jev relevance scoring
  → Exposure filtering + ranking
  → LLM
```

Jev ska inte användas för sådant som vanlig kod redan kan avgöra säkert.

# Exposure strategy

Undvik en enda hård global cutoff. Kombinera:

- minimum floor,
- top-k,
- relativ skillnad mot högsta score,
- complementary och dependent tools.

Exempel: en capability för att läsa runt en träff kan fortfarande vara relevant trots lägre score, eftersom den är ett naturligt kompletterande steg efter en träff.

Trösklar ska vara centralt konfigurerbara. Lägg dem i settings-modulen, inte som utspridda konstanter i anropsställena.

# Tool relations

Tool-registret får beskriva enkla relationer. Namnen nedan är illustrativa capability-etiketter:

```text
find_in_document may_lead_to read_around_location, go_to_location, highlight_location
follow_reference may_lead_to read_section, go_to_location
```

Relationerna används endast för retrieval och exposure. De ska inte automatiskt exekvera nästa verktyg.

# Tool descriptions

Tool descriptions måste vara semantiskt distinkta eftersom Jev använder dem för retrieval. En beskrivning ska säga både när verktyget ska användas och vad verktyget inte gör.

Följande fyra beskrivningar är exempel på hur capabilities ska skiljas åt. De är inte en kravställd ny tool-yta. Fas 0 kan mappa varje beskrivning på ett befintligt verktyg, en utökning av dess schema, eller en lucka som faktiskt saknas.

`find_in_document`

- Använd när användaren frågar var något står och positionen inte redan är känd.
- Returnera kandidater med stabil dokumentposition. Välj exakt textsökning när strängen är känd, och semantisk sökning när frågan är en betydelse.
- Gör inte: flytta vyn, markera passage, läsa omgivande kontext, eller söka i ett annat dokument än det som är identifierat.

`go_to_location`

- Använd när en sida, anchor, section eller annan position redan är identifierad och vyn ska flyttas dit.
- Gör inte: ny sökning, ny markering, eller läsning av text.

`highlight_location`

- Använd när en redan identifierad passage ska markeras i dokumentvyn.
- Säg att något har markerats eller visats först efter bekräftad klientoperation.
- Gör inte: sökning, dokumentbyte, eller läsning. Om `focus_anchor` redan markerar en lokaliserad passage ska den capabilityn återanvändas.

`read_around_location`

- Använd när en träff eller position är känd och modellen behöver kontext runt den, till exempel två stycken före, träffen och två stycken efter.
- Återanvänd text units och befintlig källäsning.
- Gör inte: flytta vyn, markera, eller starta en ny sökning.

# Multi-tool planning

Jev ska inte försöka bestämma hela tool-sekvensen.

Exempel: användaren frågar var det står om förtida uppsägning och vill se stället. Jev exponerar de capabilities som motsvarar att hitta, markera, gå till position och läsa runt träffen. LLM:en planerar ordningen, till exempel hitta, läsa kontext, navigera och markera.

Sekvensplanering är LLM:ens uppgift.

# Re-routing efter tool call

Tool retrieval får köras igen efter ett tool-resultat när nästa relevanta operation har förändrats och ingen Djup-episod redan äger en arbetsbänk.

Exempel: en sökning returnerar tre träffar. En ny bedömning kan då höja relevansen för att läsa runt en träff, gå till en position eller markera den. Capability-namnen i det exemplet är illustrativa.

Undvik ny Jev-routing efter triviala tool calls när kandidatmängden uppenbart inte har förändrats.

Inuti en Djup-episod behålls det initiala tool setet. Ny retrieval där är tool expansion, alltså ett undantag när en capability saknas, inte ett anrop efter varje resultat. Det beskrivs i [expert-chat-reasoning-episode.md](expert-chat-reasoning-episode.md). Samma retrieval och samma score-semantik används. Ingen parallell mekanism.

# Exempel

Tool-namn i exemplen är illustrativa capability-etiketter.

1. **"Gå till sida 37."** Exponera bara verktyg som navigerar till en känd sida. Ingen semantisk sökning.
2. **"Var står det om vite?"** Hitta kandidater, läs kontext runt träffen, och visa eller markera positionen. LLM:en väljer ordningen.
3. **"Vad står det i punkten som den här hänvisar till?"** Utgå från aktuell position, följ den dokumentinterna referensen till befintlig section eller anchor, läs sektionen och flytta vyn dit.
4. **"Visa motsvarande bestämmelse i @Ramavtal.pdf."** Kontexten innehåller `current_selection` och `explicit_document_id` satt till mentionens canonical ID, inte ett filnamn som fuzzy-matchas i tool-lagret.

# Observability

Logga per retrieval:

- user turn eller trace ID,
- state-filtrerad kandidatmängd,
- Jev-score per kandidat,
- vilka verktyg som exponerades och deras ranking,
- vilka verktyg LLM:en faktiskt valde,
- om LLM:en valde det högst rankade verktyget,
- Jev-latens,
- tool-resultat,
- eventuell re-routing.

Det ska gå att se till exempel att Jev rankade en hitta-capability som nummer ett medan LLM:en valde en outline-capability som nummer två. Namn i sådana loggrader är de verktyg Fas 0 faktiskt valde; exemplet `find_in_document` mot `get_document_outline` är bara en illustration.

Kalibreringssignaler:

- ett verktyg rankas systematiskt för högt eller för lågt,
- cutoff filtrerar bort verktyg som LLM:en behöver,
- beskrivningar är för lika,
- regler för kompletterande verktyg behöver justeras.

# Failure handling

Om Jev misslyckas ska dokumentnavigationen fortsätta fungera. Fallback använder den befintliga mekanismen för tool-exponering, eller en säker statisk delmängd av relevanta workspace- och dokumentverktyg.

Detta är en uttryckligen begärd fallback och gäller endast vilka verktyg som exponeras. Projektets regel mot fallbacks för LLM-, modell- och API-val gäller fortfarande:

- fallbacken får inte tyst byta LLM-provider eller modell,
- Jev är en optimering och en routingmekanism, inte en single point of failure för dokumentnavigation,
- om inte heller den befintliga exponeringsvägen kan köras ska felet synas tydligt,
- inför inte alternativa modellproviders.

# Implementation order

Fas 0: Inventera befintlig implementation. Ingen parallell funktionalitet.

Fas 1: Fastställ vilka capabilities som redan finns och vilka faktiska luckor som återstår.

Fas 2: Exponera eller utöka dokumentnavigation ovanpå befintlig implementation.

Fas 3: Inför Jev relevance scoring.

Fas 4: Inför dynamisk schema-exponering och ranking.

Fas 5: Inför re-routing efter relevanta tool-resultat.

Fas 6: Kalibrera scores och trösklar från verklig användning.

Parallella workers åt Djup är inte en fas i den här specen. De kommer efteråt, i [worker-delegationsspecen](expert-chat-worker-delegation.md), och återanvänder samma läsverktyg och identiteter.

# Acceptance criteria

1. Befintlig dokument-, workspace-, anchor-, viewer- och knowledgefunktionalitet är inventerad innan nya mekanismer byggs.
2. Nya verktyg återanvänder befintliga capabilities där de finns.
3. Ingen parallell document identity, selection state, anchor-modell eller sökindex skapas utan dokumenterat behov.
4. Chatten kan hitta, läsa, navigera och markera innehåll i dokument.
5. Explicit `@document` resolvas till canonical ID.
6. Jev rankar tillgängliga verktyg efter semantisk relevans.
7. Endast ett relevant subset exponeras för huvud-LLM:en.
8. Exponerade verktyg innehåller sina Jev relevance scores.
9. Scores används som rådgivande ranking för vilket verktyg som ska anropas.
10. LLM:en måste anropa minst ett verktyg när frågan kräver uppslag. Inget
    anrop är bara för hälsning, bekräftelse eller något som redan syns i turen.
    `search_knowledge` och `get_workspace_context` stannar synliga även när
    Jev scorar dem lågt. Hög maxscore sätter `tool_choice=required`.
11. State- och capability-filtrering sker före Jev när det kan avgöras deterministiskt.
12. Tool retrieval kan köras igen när ett tool-resultat förändrar nästa relevanta operation.
13. Jev-fel blockerar inte dokumentnavigation.
14. Routing och faktiska tool-val loggas för kalibrering.
15. Befintlig funktionalitet fortsätter fungera utan regressioner.
