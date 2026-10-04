# Live voice i SME chatten och arbetsytan

Implementera SME chatten som ett sammanhängande samtal där användaren kan prata, skriva och klicka i arbetsytan. ElevenLabs ska driva dialogen och använda Socialisms verktyg för ingest, kunskapssökning, källvisning, jämförelse, grafer och dokumentskapande. Samtalets resultat ska gå att se, redigera och återkomma till i samma workspace.

Specen avser chatten och arbetsytan. Utgå från användarens konceptbilder och befintliga SME komponenter. Simuleringsmotorn och andra produkters dialoger ingår inte i denna förändring. Ingen bakåtkompatibilitet behöver byggas för tidigare kunder.

## Konceptbilder och arbetsflöde

Använd dessa två bilder som visuell och funktionell referens:

- [Dokument med delad visning och källmarkering](assets/live-voice-chat-documents-concept.png).
- [Relationer mellan händelse, villkor och källor](assets/live-voice-chat-relations-concept.png).

Behåll expertlistan till vänster, vald expert och samtalet i vänsterpanelen samt arbetsytan till höger. Telefonknappen i inmatningsraden startar live voice för den valda expertchatten. Visa korta tillstånd som ansluter, lyssnar, talar, pausad och fel. Textinmatning och övriga verktyg ska fortsätta vara tillgängliga under röstsamtalet.

Överst väljer användaren kunskapsområde: Workspace, Allmän kunskap eller Research. Arbetsytan har vyerna Evidens, Jämförelse, Dokument och Relationer. Skapade dokument öppnas som redigerbara artefakter i samma arbetsyta. Bevara komponenternas placering, svart och guld, källnummer, flikar och delad dokumentvisning från referenserna. Följ frontendens befintliga visuella system och i18n för svenska och engelska.

Konceptbildernas avtal och siffror är exempeldata. Demonstrationer och tester ska använda tydligt avgränsade fixtures med motsvarande källankare.

### Ett sammanhängande användarflöde

1. Användaren väljer workspace och expert samt lägger till dokument. Ingeststatus visas i chatten och arbetsytan.
2. Användaren startar live voice och ställer en fråga om materialet. Agenten söker i det valda kunskapsområdet.
3. Agenten öppnar relevanta dokument och markerar avsnitten som svaret bygger på. Svaret visas i chatten med klickbara källreferenser och ges muntligt i kortare form.
4. Användaren säger exempelvis ”jämför villkoren” eller ”visa sambanden”. Samma resultat visas i jämförelsevyn eller relationsgrafen.
5. Användaren markerar ett stycke eller väljer en nod och säger ”förklara den här”. Agenten använder den aktuella markeringen.
6. Användaren ber om ett dokument. Agenten skapar ett redigerbart utkast med källhänvisningar. Användaren kan ändra det genom text, röst eller direkt redigering och exportera resultatet.

## Ansvar mellan ElevenLabs och Socialism

| Del | Ansvar |
| --- | --- |
| Samtal | ElevenLabs Agents och webbläsarens officiella SDK hanterar dialogmodell, tal, transkription, avbrott, textmeddelanden och verktygsanrop. |
| Arbetsmoment | ElevenLabs procedures beskriver när agenten ska söka, visa, jämföra, skapa och ändra. |
| Gemensamma arbetsinstruktioner | Databasens aktiva instruktioner publiceras som agentprompt och procedures. Denna leverans använder Socialisms källverktyg för kunskap; nativ Knowledge Base och RAG är avstängda så att fakta alltid går genom den verifierade källvägen. |
| Användarens material | Socialism lagrar dokument, ingeststatus, kunskap, källankare, relationer, jobb och artefakter med verifierad åtkomst. |
| Presentation | React arbetsytan visar dokument, evidens, jämförelser, grafer, diagram och utkast genom client tools. |
| Beständig historik | Socialism äger lokal chattidentitet, expertthread, meddelanden och arbetsläge. ElevenLabs conversation ID kopplas till denna historik. |

ElevenLabs ska vara den enda svarsgeneratorn i den nya SME dialogvägen. Befintliga backendtjänster återanvänds som verktyg. `execute_expert_turn()` får inte samtidigt producera ett andra dialogsvar för samma användartur. Specialistarbete som kunskapsextraktion och dokumentgenerering kan fortsätta använda projektets befintliga backendmodell.

Använd en konfigurerad väg per funktion. Ett fel ska visas tydligt och får inte tyst byta modell, röstleverantör eller dialogmotor.

## Gemensam session och arbetsläge

Koppla en beständig privat röstcanvas med titel, kund och ägare till projektets befintliga företags- eller kundworkspace och privata chatt. Canvasen håller underlag, expertthreads och artefakter; den kan skapas och återöppnas. Åtkomst kräver både chattägarskap och aktuell medlemsbehörighet till föräldraarbetsytan. Fler experter i canvasen utvidgar inte användarens dokumentbehörigheter.

Inför en beständig workspace session som binder workspace, autentiserad användare och kund, vald expertthread, lokal chattidentitet, ElevenLabs conversation ID, valt kunskapsområde, dokumentflikar, aktiv vy, markeringar, artefakter och pågående jobb. Arbetsläget ska ha en revision som ändras när användaren eller agenten ändrar det.

Under en aktiv voice session ska textmeddelanden skickas till samma ElevenLabs samtal. Testa tal, text och tal utan att skapa en ny leverantörssession. Före röststart och efter röststopp används samma lokala chatt och samma arbetsläge. Om SDK:t kräver olika anslutningar för en ren textsession och en voice session ska övergången återföra den tillåtna lokala historiken och arbetskontexten; leverantörens ID ska inte användas som produktens enda historiknyckel.

Röstsessionen binds till den valda experten. Vid expertbyte avslutas den gamla expertens röstsession, expertens egen historik behålls och arbetsytan ligger kvar. Start av röst hos den nya experten använder den nya expertens behöriga kontext. Den tidigare experten får inte fortsätta tala efter bytet. Sena meddelanden och verktygsresultat ska kontrolleras mot ursprunglig expertthread och sessionsgeneration. De får sparas till rätt historik eller artefakt, men får inte skriva över den nya expertens aktuella arbetsläge eller börja spela ljud.

Bevara befintligt långtidsminne för kund och expert samt Minnen-knappen. Återanvänd expertminnestjänstens läsning och skrivning genom verktyg eller turhändelser. En slutlig tur får inte skrivas flera gånger när samma leverantörsevent återlevereras. Expertminne och källbelagd evidens har olika betydelse; ett minnesresultat får inte presenteras som en verifierad dokumentkälla. Se [Expertminne](../guides/expert-memory.md).

Klick, text och röst ska använda samma kommandon och objektidentiteter. Agenten får kontextuppdateringar om aktiv vy, öppna dokument, vald nod och markerat källankare. Fånga relevant arbetsläge när användarturen tas emot, så att ”den här” inte byter betydelse om användaren väljer något annat medan ett verktyg arbetar.

### Meddelanden och avbrott

Visa preliminär transkription som preliminär och spara det slutliga användarmeddelandet en gång. Hantera strömmande och slutliga agentsvar utan dubletter. När agenten avbryts ska `agent_response_correction` korrigera det som faktiskt sades. En separat, tydligt märkt sammanställning eller artefakt kan innehålla mer detaljer än den muntliga förklaringen. Se [Client events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-events).

Att pausa mikrofonen stoppar ljudinmatningen och behåller chatten, arbetsytan och jobben. Att avsluta voice avslutar leverantörssessionen men behåller den lokala historiken. Återupptagning använder aktuell behörig kontext och visas tydligt som en ny röstanslutning när det behövs.

## Verktyg för arbete och presentation

Följande namn och kontrakt kopplas till befintliga tjänster där sådana finns. I den lokala implementationen publiceras alla som ElevenLabs client tools. Presentationsverktyg körs i gränssnittet; verktyg med serverarbete skickas av webbläsaren till den autentiserade backendens sessionsbundna verktygsroute. Det gör att även serverarbetet fungerar utan en publik webhook eller tunnel. Ett generellt MCP lager behövs inte för denna leverans.

| Verktyg | Utförande | Resultat |
| --- | --- | --- |
| `open_ingest_picker` | Klient | Öppnar uppladdningsväljaren; användaren väljer filer eller anger URL. |
| `ingest_source` och `get_job_status` | Server | Startar inläsning respektive läser beständig status. Returnerar jobbid och källidentitet. |
| `search_knowledge` och `read_source` | Server | Hämtar tillåtna fakta, utdrag, kunskapsluckor och källankare från valt område. |
| `start_research` | Server | Startar befintlig researchväg med objective, tillåten kontext och idempotensnyckel; returnerar beständig Run, Attempt och jobbreferens. |
| `show_evidence` | Klient | Visar evidens med källa, härkomst och tillgänglig status. |
| `show_document` och `focus_anchor` | Klient | Öppnar dokument, väljer sida och markerar ett exakt källavsnitt. |
| `compare_sources` och `show_comparison` | Server och klient | Bygger och visar jämförelse med hänvisning för varje uppgift. |
| `get_relations` och `show_relations` | Server och klient | Hämtar och visar relationer med källankare och tydligt angiven tolkning där det behövs. |
| `render_chart` | Server och klient | Återanvänder befintliga diagram med underliggande data och källor. |
| `show_knowledge` | Klient | Visar fakta, frågor och svar, anteckningar och kunskapsluckor. |
| `create_document`, `revise_document` och `export_document` | Server | Skapar eller ändrar en versionshanterad dokumentartefakt och exporterar en angiven revision. |
| `show_artifact` | Klient | Öppnar ett sparat dokument eller annat resultat i arbetsytan. |

Serverresultat ska vara strukturerade och innehålla operationens identitet, verklig status samt berörda källor, källankare, artefakter och jobb. Stora dokument skickas genom tillåtna referenser och relevanta utdrag. Verktygsresultat får inte innehålla godtycklig HTML eller skript som agenten kan köra i arbetsytan.

Aktivera Wait for response för presentationsverktyg när nästa yttrande beror på visningen. `show_document` ska svara success först när rätt dokument och ankare visas. Agenten får då säga att avsnittet är öppet. Vid visningsfel ska agenten få det faktiska felet och arbetsytan visa en begriplig felstatus. Se [Client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools).

### Behörighet och återupprepade anrop

Backend ska utfärda åtkomst till den privata agenten först efter Socialism inloggning och kontroll av arbetsytan. Detta gäller både ren textanslutning och voice. Använd serverutfärdad WebRTC conversation token för voice och dokumenterad privat textanslutning med serverutfärdad signed URL där SDK:t kräver det. ElevenLabs API nyckel stannar i backend. Se [Authentication](https://elevenlabs.io/docs/eleven-agents/customization/authentication) och [React SDK](https://elevenlabs.io/docs/eleven-agents/libraries/react).

Serverarbetets client tools anropar backend med användarens vanliga inloggningsbehörighet, lokal sessionsidentitet och det bundna ElevenLabs conversation ID:t. Backend verifierar användare, kund, arbetsyta, expert, sessionsgeneration och giltighetstid för varje anrop. Anropet binds också till den sparade användarturens frysta arbetsläge. Leverantörens anslutningsuppgifter ska inte ge generell åtkomst till backend.

Backend härleder behörigheten från den verifierade sessionen. Agentvalda kund, workspace eller användar-ID:n är inte auktorisering. Varje objekt läses och ändras med serverns åtkomstkontroll; underlagets befintliga kund- och arbetsytebehörighet ska bevaras, inklusive tillåtna delade företagsdokument; privat historik och artefakter kräver dessutom chattägarskap. Källreferenser från Allmän kunskap och Research får bara göras tillgängliga om den inloggade användaren har tillgång till dem.

Vid expertbyte eller avslutad agentsession återkallas dess serverregistrerade verktygsbehörighet. Nya anrop med den gamla behörigheten ska nekas även om tokenens tidsgräns ännu inte passerats. Redan mottagna beständiga jobb får slutföras under sin ursprungliga objektåtkomst. Jobbhändelser sparas till rätt workspace och expertthread; kontextuppdateringar skickas bara till en aktuell behörig anslutning.

Varje skapande eller ändrande operation ska ha en beständig idempotensnyckel. Återlevererade anrop ska återge samma jobb eller resultat. En operation ska inte köras en gång i en server tool och en gång till i en client tool. Klientens arbetsläge ska avvisa eller hantera föråldrade revisioner utan att skriva över senare ändringar.

## Ingest och kunskap under samtalet

Återanvänd `POST /underlag`, `document_ingest` och lagrad ingeststatus. Behåll befintliga filformat och visa verkliga tillstånd såsom pending, running, ready, partial, failed, empty och needs_ocr med användarvänlig översättning. Skannade PDF dokument kräver en uttrycklig OCR lösning för att bli sökbara; nuvarande ingest har ingen sådan väg. Visa detta som ett konkret läsbarhetsproblem och presentera inte filen som färdig kunskap.

Ingest, research och dokumentskapande ska starta snabbt och återge ett jobbid när arbetet fortsätter i bakgrunden. Jobben och resultaten ska bestå om voice sessionen avslutas. Använd projektets jobbhändelser för att uppdatera UI och `sendContextualUpdate` för att ge agenten bakgrundsinformation. En sådan uppdatering ska inte avbryta användaren eller ensam skapa en ny agenttur. Vid nästa naturliga tur kan agenten använda resultatet.

`start_research` ska använda befintliga Run och Attempt samt researchstartens produktvillkor och beständiga claims. Återanvänd befintlig researchmotor, evidensfrysning och progress events. Att välja Research som kunskapsområde är en kontextändring och startar inte i sig ett nytt researchjobb.

Nyimporterade dokument i en pågående voice session ska kunna sökas genom Socialisms verktyg utan omstart. Förutsätt inte att en ändring i ElevenLabs Knowledge Base automatiskt uppdaterar det pågående samtalet. KB overrides gäller vid samtalsstart och ersätter den konfigurerade listan. Se [Overrides](https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides).

ElevenLabs native bilagor kan komplettera senare. De får användas först efter att stöd för vald SDK version, modell och voice mode verifierats. Den kompletta första leveransen ska fungera genom Socialisms ingest och sökverktyg.

## Dokument och källreferenser

Återanvänd PDF.js, `PdfKnowledgeViewer` och normaliserade ankare från dokumentkunskapen. Lyft återanvändbar visning ur uppladdningsmodalen till arbetsytan. Dokument ska kunna visas i egna flikar och två dokument sida vid sida, med oberoende sidnummer och zoom.

Källnummer ska vara stabila inom presentationen och peka på en stabil källidentitet och ett exakt ankare. Samma referens används i chatt, evidens, jämförelse, graf och utkast. Ankare är källtypsberoende: PDF använder sida och markering; text, webbkällor och research använder ett motsvarande block eller utdrag från rätt version eller fryst evidens. När en referens väljs ska rätt källa och avsnitt visas. Blanda inte om källnummer när resultatet sorteras efter risk eller relevans.

Spara dokumentrevision eller innehållshash tillsammans med ankaret. Om dokumentet ändras och ankaret inte längre matchar ska länken visas som inaktuell. Agenten får inte säga att en omarkerad eller oåtkomlig källa är verifierad.

## Jämförelse och grafpresentation

Jämförelse är en ny generell funktion. Ange vilket sakområde som jämförs, vilka källor som ingår och uppgifternas ankare. Saknad uppgift ska visas som okänd. Låt användaren öppna varje celluppgift i dokumentet. Agentens bedömning av konflikt eller prioritet ska framgå som en bedömning med de uppgifter den bygger på.

Grafpresentation omfattar både diagram över data och en kunskapsgraf med noder och relationer. Återanvänd `SpinndoktorChartSvg` för hbar, donut, stat_number och radar. Den generella relationsgrafen är ny; befintlig `QuestionEvidenceGraph` är en vy från fråga till evidens och räcker inte för denna funktion.

Relationsgrafen ska kunna visa händelse, villkor, effekt och berörda källor enligt konceptbilden. Varje relation ska ha stabil identitet, typ och källreferens. Skilj källbelagd relation från agentens tolkning. Att två uppgifter visas i samma graf är inte i sig ett belagt orsakssamband. Klick på en nod eller relation fokuserar objektet och uppdaterar agentens kontext; röstkommandon ska kunna göra samma sak.

## Skapande och redigering av dokument

Inför en beständig dokumentartefakt med titel, typ, innehåll, stabila blockidentiteter, källreferenser och revision. Agenten ska kunna skapa ett underlag, en sammanställning eller ett brev från det aktuella samtalet och dess tillåtna källor.

Öppna färdigt utkast i arbetsytan och låt användaren redigera direkt. Ett röstkommando som ”förkorta andra stycket” riktas mot ett identifierat block och en angiven revision. En samtidig manuell ändring ska ge en synlig revisionskonflikt och får inte tyst skrivas över. Varje lyckad ändring skapar en ny revision och behåller källhänvisningarna där de fortfarande gäller.

Exportera en uttryckligen vald revision till DOCX och PDF. Exporten ska bevara text, rubriker och användbara källhänvisningar. URL till skapad fil ska gå genom den befintliga behörighetsmodellen. Existerande `POST /reports` producerar rapporter för särskilda produktflöden och ersätter inte denna generella dokumentfunktion.

## Procedures och felhantering

Använd fokuserade free form procedures för att förstå uppgiften, söka kunskap, välja presentation och förklara resultat. Använd korta structured procedures där ett särskilt verktygssteg ska utföras, exempelvis skapa dokument eller jämförelse. Verktyget ska ha konkreta referenser i procedure konfigurationen.

I structured procedures placeras villkor i If före Tool step. Tool step kör verktyget och kan inte villkoras bort genom prosa i instruktionen. Lägg en tydlig `on_failure` som rapporterar felet. Säkerställ också att efterföljande steg inte meddelar att arbetet lyckats efter ett fel. Ett lyckat HTTP anrop med status queued är en mottagen beställning, inte en färdig artefakt. Se [Structured procedures](https://elevenlabs.io/docs/eleven-agents/customization/procedures/structured-procedures).

Verifiera att vald dialogmodell stöder forced tool choice för övergångar och slutförande av structured procedures. Håll procedures fokuserade: ElevenLabs håller instruktionerna från de fem senast startade procedurerna i kontext. Ärendets tillstånd och resultat ska därför kunna hämtas från Socialism. Se [Procedures](https://elevenlabs.io/docs/eleven-agents/customization/procedures).

Agentkonfiguration, procedures och verktygskontrakt ska versionshanteras med en dokumenterad deployment. Hemligheter lagras i servicekonfigurationen. Dialogprompt och procedure innehåll som används vid runtime ska komma från projektets `prompt_fields` och `prompt_overrides`, genom `require_active_prompts` och `render_prompt`. Agentdeployment eller serverkontrollerad initiering ska publicera en identifierad snapshot från denna källa till ElevenLabs. Spara promptversion och agentversion för samtalet. Repo kan innehålla schemas och deploymentverktyg, men får inte bli en andra oberoende källa för aktiv prompttext. Följ [backend AGENTS](../../backend/AGENTS.md).

## Befintlig kod att återanvända

| Område | Ingång i repositoryt | Återanvändning |
| --- | --- | --- |
| SME chattyta | `frontend/src/products/sme/SmeMessengerPage.tsx`, `SmeChatPane`, `SmeConversationList`, `components/chat/MessengerChat.tsx` | Expertthread, meddelanden och chattytans grund. |
| Beständiga turer | `backend/app/services/sme_expert_turns.py` | Accept, idempotens och lagringsprinciper. Håll befintlig svarsexekvering utanför ElevenLabs turväg. |
| Åtkomst | `backend/app/auth/scope.py`, `/me` och frontendens AuthProvider | Autentiserad användare, kund och objektåtkomst. |
| Ingest | `backend/app/api/underlag.py` och tjänsten för `document_ingest` | Upload, filhämtning, status och bakgrundsarbete. |
| Källvisning | `frontend/src/components/underlag/PdfKnowledgeViewer.tsx`, `UnderlagPickerModal`, `DocumentKnowledgePanel` | PDF, källankare och dokumentkunskap. |
| Research och evidens | `backend/app/api/execution.py`, `ResearchMonitorPanel`, `EvidenceSetView`, `EvidenceItemCard` | Researchstatus, resultat och fryst evidens. |
| Diagram | `backend/app/services/spindoctor_mcp_tools.py`, `SpinndoktorChartSvg` | Befintliga diagramkontrakt och renderer. |
| Rapporter | `backend/app/api/reports.py` | Jobb och exportprinciper där de passar. Ny dokumentmodell behövs. |

Inför implementation ska aktuella filer och tillämpliga AGENTS kontrolleras igen. Det lokala checkout som granskades har andra pågående ändringar; implementera i en avgränsad branch eller worktree och bevara dessa ändringar.

## Leveransordning

1. Verifiera SDK och privat voice session, kombinationen röst och text, serverbehörighet för tools och transkripthändelser. Lås vald SDK version och dokumentera konfigurationen.
2. Bygg beständig workspace session, gemensamma kommandon, verktygsadapter och arbetsyta runt befintlig SME chatt.
3. Leverera ingest, kunskapssökning, evidens, dokumentflikar, källmarkering och delad visning.
4. Leverera jämförelse, relationsgraf och återanvända diagram med samma källreferenser.
5. Leverera skapande, redigering, revisioner och export av dokument samt sammanhängande end to end verifiering.

Varje steg ska gå att demonstrera, men hela specen är färdig först när alla fem steg och nedanstående kriterier är uppfyllda. Uppdatera svensk operatörsguide i `knowledge/manual/`, motsvarande engelska UI texter och utvecklardokumentation för agentkonfiguration och verktyg.

## Godkännandekriterier

1. Telefonknappen startar live voice för vald expert utan att chatthistorik, öppna källor eller arbetsläge försvinner.
2. Tal, text och tal fungerar i samma aktiva ElevenLabs conversation. Paus och avslut av röst bevarar det lokala arbetet.
3. Expertbyte stoppar tidigare expertens röst och bevarar separata expertthreads i samma workspace.
4. Slutliga användarmeddelanden och agentsvar lagras utan dubletter. Ett avbrott korrigerar transkriptet och stoppar fortsatt ljud.
5. Nytt underlag kan laddas upp och användas genom sökverktyg i samma pågående voice session efter färdig ingest. Partial, failed och needs_ocr visas korrekt.
6. Samma fråga med olika kunskapsområde använder rätt källmängd. Nekad eller manipulerad objektåtkomst ger fel utan innehållsläckage.
7. Ett källnummer i chatt, graf, jämförelse eller utkast öppnar samma källrevision eller evidenssnapshot och rätt avsnitt med ankare för källtypen. Två dokument kan visas sida vid sida.
8. En klickad markering och en följande röstfråga använder det valda objektet. En senare UI ändring byter inte en redan mottagen turs referent.
9. Jämförelsen visar saknade uppgifter som okända och varje faktisk uppgift har en fungerande källreferens.
10. Relationsgrafen har verifierbara källor och tydlig skillnad mellan uppgift och tolkning. Diagram använder samma underliggande data som sitt verktygsresultat.
11. Skapande av dokument ger en sparad, redigerbar artefakt. Röst och manuell redigering skapar revisioner; samtidiga ändringar hanteras utan dataförlust.
12. DOCX och PDF export av en vald revision innehåller samma text och källhänvisningar som arbetsytan.
13. Återlevererade skapandeanrop ger samma jobb eller artefakt och skapar inget extra dokument.
14. Ett klart bakgrundsjobb uppdaterar UI och agentkontext utan att avbryta användarens tal eller skapa ett påhittat användarmeddelande. Resultatet kan återöppnas efter avslutad voice.
15. Ett misslyckat UI verktyg eller backendjobb ger tydlig felstatus. Agenten påstår inte att en källa är öppnad eller ett jobb är klart innan det stämmer.
16. Privat åtkomst kontrolleras i både text och voice. Ingen ElevenLabs API nyckel eller sessionshemlighet exponeras i klientbundle, transkript eller loggar. Utgången eller manipulerad behörighet nekas.
17. UI följer konceptbildernas layout, projektets visuella system och i18n. Tangentbord och smal skärm kan använda nödvändiga funktioner utan överlappning.

Kör relevanta backendtester, frontendtester, lint och kunskapsvalidering enligt repositoryts CI. Lägg meningsfulla integrationstester vid gränserna för auktorisering, idempotens, sessionstillstånd och verktygsresultat. Verifiera dessutom ett riktigt ElevenLabs röstsamtal med ingest, källvisning och dokumentändring; enbart mockade event visar inte att voice integrationen fungerar.

## Dokumentation för ElevenLabs

Kontrollerat mot officiell dokumentation den 3 oktober 2026. Konfigurationen för vald SDK version ska verifieras igen vid implementation.

- [Quickstart](https://elevenlabs.io/docs/eleven-agents/quickstart) och [React SDK](https://elevenlabs.io/docs/eleven-agents/libraries/react).
- [Procedures](https://elevenlabs.io/docs/eleven-agents/customization/procedures) och [Structured procedures](https://elevenlabs.io/docs/eleven-agents/customization/procedures/structured-procedures).
- [Client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools) och [Webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools).
- [Client events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-events) och [Client to server events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-to-server-events).
- [Authentication](https://elevenlabs.io/docs/eleven-agents/customization/authentication), [Voice token](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get-webrtc-token) och [Dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables).
- [Knowledge Base](https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base), [RAG](https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base/rag) och [Overrides](https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides).
- [SDK bilagor den 31 augusti 2026](https://elevenlabs.io/docs/changelog/2026/8/31) och [SDK utgående bilagor den 7 september 2026](https://elevenlabs.io/docs/changelog/2026/9/7).
