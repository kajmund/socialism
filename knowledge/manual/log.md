# Manual update log

## 2026-09-03

* **Expertgranskning**: Du kan ladda upp ett eget underlag (txt, md, PDF eller Word) i stället för att bara klistra in text. Filerna är personliga. I rapporten visas dokumentet formaterat.

## 2026-09-02

* **Expertgranskning**: Ny yta i vänstermenyn. Klistra in en text, välj en märkt expertpanel och kör en granskning. Rapporten öppnas med Spinndoktor. Administratör ser länken alltid.

## 2026-09-01

* **Verktyg**: Prompttexter i konfigurationer gäller direkt per kund och språk. **Aktivera** styr bara SSR-temperatur, ankare och grunddata — inte LLM-promptarna.
* **Hjälpchatten**: Assistenten använder prompttexterna för den organisation du är inloggad som (administratör/användare respektive bolag).
* **Inloggning**: Efter inloggning landar du direkt i appen. Moduler väljs i vänstermenyn, inte på en separat **Välj modul**-sida.
* **Due Diligence (bolag)**: Under **Kandidater** kan du fälla ut ett bolag och ladda upp **årsredovisningar** (PDF eller bild). Filerna går att ladda ner och ta bort.
* **Rapporter**: Färdiga rapporter sparas i kundens fillager per modul, samma ställe som årsredovisningarna.
* **Socialism**: Produktnamnet i gränssnittet är **Socialism** (inte Opinionssimulator). På inloggningen står **Agentdriven socialism.**
* **Due Diligence**: Förkortningen **DD** är utbytt mot **Due Diligence** i gränssnittet (menyer, knappar, jobbtyper och rapporter).
* **Jobb**: Avslutade bakgrundsjobb kan arkiveras (enskilt eller alla på en gång) så listan blir ren. Resultatet ligger kvar. Visa arkiverade och återställ om du behöver historiken igen.
* **Navigering**: Huvudmenyn ligger vertikalt till vänster. Modulernas länkar (politisk simulering respektive Due Diligence) syns där när modulen är påslagen för kunden.

## 2026-08-31

* **Användare**: Sidan **Användare** ligger i huvudmenyn (inte under **Verktyg**). Där skapas också **bolag** innan man bjuder in användare.
* **Verktyg**: Under **Panelkatalog** → **Sub-frågor** raderar **Ta bort** frågan om den inte används i en körning/rapport. Ta bort körningen först om den blockeras.
* **Inloggning**: Inloggning sker med **e-postlänk** (magic link). Statiska lösenordskontona `admin`/`user`/`bolag` är borttagna. En administratör bjuder in nya användare under **Användare**.
* **Inloggning**: Vilken yta du landar på styrs av kundens tilldelade moduler under **Verktyg** → **Kunder**. Två eller fler moduler ger sidan **Välj modul**. Inga tilldelade moduler visas som ett fel på inloggningen.
* **Verktyg**: Default-expertprofiler i panelkatalogen kan delas mellan moduler (samma profil, flera moduler). Sub-frågor är fortfarande unika per modul.

## 2026-08-30

* **Verktyg**: Under **Kunder** slår administratören på och av produktmoduler per kund. Rapportflikar och bolag-menyn följer kundens moduler.
* **Verktyg**: Under **Panelkatalog** redigerar administratören sub-frågor och default-expertprofiler för expertpanelen. Inaktiverade rader används inte i nya körningar. Ordningen måste vara unik — två rader kan inte dela samma nummer.
* **Due Diligence (bolag)**: Relaterade bolag från Allabolag visas inte i kandidatuppgifter, panelunderlag eller rapport. Experterna motiverar poängen med fakta, inte bara siffran. När de räcker upp handen säger de också varför frågan är deras kärnkompetens. Finns nyckeltal i grunddata märks poängen **Grunddata** — inte en slumpmässig webbträff.
* **Due Diligence (bolag)**: Under Research → Koncern visas bolagen som en sökbar lista i strukturordning med KPI-sammanfattning och detaljer till höger (styrelse och understruktur). Den tidigare koncernkartan är borttagen.
* **Due Diligence (bolag)**: Under Research → Personer visas personerna i en lista med sök och filter. Välj en person för att se dossiern till höger (uppdrag i/utanför koncernen och sociala träffar). **Utred valda** och **Utred alla** ligger uppe till höger, samma plats som koncernknapparna.
* **Due Diligence (bolag)**: Omresearch kräver **Rensa research** först. Du kan inte kartlägga koncernen om, och inte utreda personer igen när alla valda redan är utredda, förrän dossiern är rensad. **Kartlägg fler** fungerar fortfarande när det finns kvarvarande bolag.
* **Due Diligence (bolag)**: Resultat har två flikar: **Live-panel** (utfrågningen) och **Rapport**. En ny körning tar bort den gamla rapporten från körningen och visar liveflödet; den färdiga rapporten ligger kvar under Rapporter. Spinndoktor öppnar den aktuella rapporten i fullbredd. Tiden på rapporten är hur lång genereringen tog, inte tiden sedan första utkastet.
* **Due Diligence (bolag)**: Övriga räkenskapsposter under ett kandidatbolag visas som en tabell per år.
* **Due Diligence (bolag)**: Översikten visar bara kampanjens namn. Sökbriefen syns inte där.
* **Due Diligence (bolag)**: Körningar är uppdelade som i politikmodulen: sök och filter på listan, konfiguration med expertpanel och start, research i egen flik.
* **Due Diligence (bolag)**: Utred person söker efter personen på LinkedIn, Facebook, Instagram, X och TikTok i stället för en allmän webbsökning.
* **Due Diligence (bolag)**: Utred person hämtar uppdragen från Allabolags befattningssidor. Tidigare sökte jobbet bolagsnamn, så personer med flera bolag kunde felaktigt hamna under Inte hittat.
* **Due Diligence (bolag)**: Personens uppdrag listar alla bolag från Allabolag, även de som redan finns i koncernen. Taket är 25 bolag per person.
* **Due Diligence (bolag)**: Körningen har en Research-flik med Koncern och Personer. Personutredningen visar lista och dossier sida vid sida. Revisorer får en not om att den långa listan beror på revisorsrollen.

## 2026-08-29

* **Due Diligence (bolag)**: Research hämtar hela koncernträdet från Allabolag (även Academic Work och utländska bolag) och slår upp nyckeltal per svenskt bolag. Kartan ritar upp till 25 bolag per omgång, med moderbolaget till vänster. Finns fler kvar kan du kartlägga nästa omgång. Personerna i styrelserna samlas som en sidoeffekt. Relaterade bolag utanför koncernen tas inte med.
* **Due Diligence (bolag)**: Kandidatlistan är hopfälld. Fäll ut ett bolag för att se uppgifterna. Räkenskaperna visas som staplar per år, likadant som i Due Diligence-rapporten.
* **Due Diligence (bolag)**: På experten öppnar du verktygsvalen med skiftnyckeln i topbaren.

## 2026-08-28

* **Due Diligence (bolag)**: Expertchatten avbryts inte längre om ett bolagsuppslag saknar organisationsnummer eller misslyckas — experten får felet och kan fortsätta.
* **Due Diligence (bolag)**: Experter googlar inte omsättning, resultat eller anställda om de redan finns i kandidatens grunddata. Finansiell hälsa märks då **Grunddata** i stället för **Webb**.
* **Due Diligence (bolag)**: Spinndoktor i live-panelen skriver bara sin egen replik — inte påhittade expertnamn, roller eller poäng. Experterna räcker upp handen per delfråga.
* **Due Diligence (bolag)**: På experten väljer du vilka verktyg den får använda i chatt och i expertpanelen (bolagssök och webbsök). Standard är alla.
* **Due Diligence (bolag)**: Om ett organisationsnummer inte finns hos Allabolag fortsätter bolagssökchatten — den avbryts inte.
* **Due Diligence (bolag)**: Bolagssökchatten kraschar inte längre när assistenten läcker verktygs-XML eller lämnar ett tomt svar efter sökningen.
* **Due Diligence (bolag)**: En expertpanel sparas direkt när du valt experter — inget bakgrundsjobb.
* **Due Diligence (bolag)**: Due Diligence-rapporten märker inte längre poäng med **OKF-manual**. Källbrickorna är **Webb**, **Grunddata** eller **Modellbedömning**.
* **Due Diligence (bolag)**: Due Diligence-rapporten visar räkenskaper som staplar per år, så omsättning, resultat och andra nyckeltal kan jämföras mellan åren.
* **Due Diligence (bolag)**: Fliken **Körningar** listar en körning per kandidat. Du öppnar **Resultat**, går till **Konfiguration** eller tar bort körningen, likadant som i politikmodulen.
* **Rapporter**: Har kontot både politik och Due Diligence delas rapportlistan upp i flikar. Har kontot bara en modul visas bara den modulens rapporter.
* **Due Diligence (bolag)**: Kandidatbolag visar F-skatt, moms, styrelse, koncern, varumärken, SNI, händelser och flera års räkenskaper, inklusive föreslagen utdelning och övriga nyckeltal, när uppgifterna finns i bolagsregistret.
* **Due Diligence (bolag)**: I bolagssöket kan du avmarkera enskilda träffar eller **Avmarkera alla**. Chatten går att skrolla när träfflistan syns.
* **Due Diligence (bolag)**: Experter, expertchatten och Spinndoktor kan slå upp bolagsuppgifter (omsättning, resultat, anställda) när de bedömer ett målbolag.
* **Due Diligence (bolag)**: Experter i chatt och panel har samma webbsök och Wikipedia som politik-personas kan få i en körning, utöver bolagsuppslag.
* **Due Diligence (bolag)**: Bolagssök i kampanjen är en chatt. Du beskriver vilka bolag du söker, väljer bland träffarna och lägger dem i kampanjen. Sökbriefen visas i översikten och kan inte ändras där.
* **Due Diligence (bolag)**: Kampanjer kan tas bort från listan efter bekräftelse.
* **Due Diligence (bolag)**: I en kampanj sker bolagssök i en modal. Du väljer kandidater bland träffarna och lägger dem i kampanjen. Sökkriterierna visas i översikten och kan inte ändras där. Kampanjen är uppdelad i flikarna Översikt, Kandidater och Expertpanel.
* **Due Diligence (bolag)**: Menyn täcker hela Due Diligence-flödet — Experter, Expertpaneler, Kampanjer, Rapporter, Återkoppling och Jobb. Rapporter och jobb visar bara bolagets egna poster.

## 2026-08-27

* **Rapporter**: Spinndoktorn tar mer initiativ — hämtar underlag med sina verktyg och lägger kort på rutnätet i stället för att fråga tillbaka.
* **Körningar**: Resultatet av en körning visas med flödet till vänster och aktiviteterna till höger. Du kan välja **Flöde**, **Aktivitet** eller **Båda**. Samma växling finns i live-vyn medan simuleringen körs. Populationen ovanför flödet är ihopfälld och kan öppnas; injektorer likaså.

## 2026-08-26

* **Körningar**: I live-flödet syns den som gillade eller ogillade en kommentar med namn och initialer, och den öppnade kommentaren säger *Gillat av …*.
* **Körningar**: Live-flödet sorterar händelser per dag efter klockslaget (senaste överst). Klockan följer händelseordningen, så ett inlägg gillas inte före det skapats.
* **Rapporter**: En klar rapport öppnas direkt i Spinndoktor. På rapporten finns **Full bredd** så den kan fylla ut ytan.

## 2026-08-24

* **Körningar**: Live-flödet under en pågående simulering visar namn från populationen (inte agentnummer), nyaste händelsen överst och gillade inlägg ihopfällda. Efter körningen öppnas samma flöde med radiosymbolen till vänster om **Beställ rapport** på försökskortet.
* **Körningar**: I live-flödet är gillade kommentarer ihopfällda och kan öppnas. Kommentarer och inlägg visar samma gilla-, ogilla- och dela-tummar som i det färdiga flödet. Följ-händelser slår upp namnet på den som följdes.
* **Körningar**: Live-flödet visar inte längre att agenter skapades i simuleringen.
* **Körningar**: Gilla/ogilla/dela i live-flödet nämner vems inlägg eller kommentar det gäller, t.ex. *Cecilia Lindholm gillade Rickard Bergmans inlägg*. Klicka på ordet **inlägg** eller **kommentar** för att läsa texten.
* **Körningar**: När någon skriver en kommentar står det vems inlägg den hör till, t.ex. *Viveca Abrahamsson skrev en kommentar på Rickard Bergmans inlägg*. Kommentarer på det injicerade inlägget nämner avsändaren, t.ex. *Socialdemokraternas inlägg*.

## 2026-08-22

* **Populationer:** Maxstorlek i population builder och API höjd från 40 till 100 medlemmar (standard 12 oförändrat).
* **Körningar**: Antal reaktionsronder per dag ställs in med stegare (1–12) i stället för fem fasta prickar. Standard för nya dagar är fortfarande 3.

## 2026-08-21

* **Körningar**: En **tyst dag** avslutar nu den gated reaktionsperioden för föregående budskag — hela populationen kan reagera fritt igen tills nästa injektion. Passiv-uteslutning och kommentarsspärr (för agenter utan tidigare engagemang) gäller inte längre genom tysta tickar.
* **Körningar**: Agenter som engagerat sig minst en gång under en simulering **behåller** rätten att kommentera resten av körningen — äldre trådar tystnar inte längre bara för att ett nytt budskag injiceras. Agenter som aldrig reagerat saknar fortfarande kommentarsverktyget tills de engagerar sig.
* **Personas**: Bibliotekslistan döljer population-genererade personas tills du väljer **Spara till bibliotek** (population eller profil). Namnkatalogen för stub-generering har utökats.

## 2026-08-20

* **Rapporter**: I Spinndoktor fyller rutnätet hela sidan. Chatten och rapportpanelen ligger flytande ovanpå och kan döljas var för sig. Rapportens sidhuvud (titel, status, ta bort) visas inte. Växlingen är vanliga knappar — **Spinndoktor** i rapportens sidhuvud, **Rapport** i chattrutan. Varje widget har kopiera och stäng. Rutnätet sparas per rapport; **Rensa rutnät** tömmer det.
* **Rapporter / Flöde (Fas 1b)**: **Ämnesstatus per inlägg** — medborgarinlägg klassas som *på ämne* eller *ämnesglidit* utifrån testbudskapets nyckelord; kommentarer ärver föräldra-inläggets status. Ton/stil bygger på alla reaktioner *på ämne* (inkl. egna inlägg om budskapet, inte bara kommentarer på injektionen). Rapportavsnittet **Ämnesdrift** visar staplar från verkliga per-inlägg-räkningar; citat har tagg *På ämne* / *Ämnesglidit*. I **Flöde** syns samma status som kantmarkering och pill i klassificeringspanelen.

* **Rapporter**: Ton och mottagande bygger på **reaktioner på ämne** (kommentarer på injektionen, på-ämne medborgarinlägg och svar i sådana trådar), inte ämnesglidit. Ny förklaring högst upp i rapporten. Negativ ton kan beskrivas som missnöjd/uppgiven i stället för kritisk när stilen dominerar.

## 2026-08-19

* **Rapporter**: Spinndoktor (fas 4-prototyp) — chatt till vänster, panorérbart rutnät med grafer, anteckningar och rapportklipp; referenspanel för HTML-rapporten; SCB och webbsök i chatten.
* **Inloggning**: Appen kräver inloggning. Två roller — administratör (`admin`) ser **Verktyg** och konfiguration; användare (`user`) gör inte det. Ingen registrering.

## 2026-08-16

* **Populationer**: Ton kommer bara från grunddata. Den hårdkodade skrivsättslistan som tidigare skrev över röst är borttagen. Standardlistorna för **Ton** och **Förtroende** är mer balanserade (orörda listor i befintliga konfigurationer uppdateras).
* **Rapporter**: Spinndoktor kan anropa verktyg för testbudskap, körningsfakta, sök i flödet, intervjuer och enskilda medborgare.
* **Konfigurationer**: Redigeraren följer mockupen — kompakt sidhuvud (namn, språk, aktiv), sökbar lista för promptfält och vänstermeny för känslighet/rapportgränser.
* **Körningar**: SSR-ankare läggs till från flödet (sköld och stjärna på kommentarer). Den gamla listan under resultatet är borttagen.
* **Körningar**: Öppna resultat följer mockupen — tillbaka-länk, försökskort, variantflikar, översiktsrad och jämför-knapp.
* **Körningar**: Listan följer mockupen — ingress, sök/filter/sortering, A/B-märken och kortlayout.
* **Admin**: Ny mockup — Rutnät/Lista på Körningar, Konfigurationer, Ankarset, Populationer, Budskap, Jobb, Rapporter, Feedback och Personas.
* **Konfigurationer**: Flikar uppdelade i Innehåll & ton, Känslighet & rapportgränser, Ankare och Grunddata.
* **SSR-ankare**: Etikettordlista (delade etiketter per typ/språk), flik Ankarpool och flik Flaggade.
* **Körningar**: I resultat kan fel SSR-klassificering flaggas; granskas under Flaggade i ankarset.

## 2026-08-14

* **Rapporter**: Verdict-kalibrering är dold på rapportsidan.

## 2026-08-13

* **Personas**: I kompositörens chatt och intervju föreslår assistenten tre knappar efter varje svar (följdfrågor i intervju, vardagsrepliker i in-character) och som start när tråden är tom.
* **Personas**: Den svarta live-promptlisten under chatten i arbetsläge är borttagen så profil och chatt får mer plats.
* **Rapporter**: Spinndoktor (fas 1) — chatt kopplad till en klar rapport med växling Rapport/Spinndoktor i sidhuvudet, valfri rapportcanvas som scrollar till avsnitt, historik per rapport.

## 2026-08-11

* **Hjälp**: Assistenten får tonetiketter från aktiv konfiguration (grunddata-katalog och SSR ton/stil) och kan lista dem i chatten.
* **Körningar**: Reaktionsmodellens stratifierade urval tar hänsyn till både distrikt och lutning när alla medlemmar har känd lutning; annars distrikt-only.
* **Populationer**: Fingeravtryck visar faktisk sammansättning (medlemmar), inte slider-mål. Recept är fryst snapshot; **Redigera recept** är borttaget — skapa ny population för annan fördelning.
* **SSR-ankare**: Publicering kräver minst åtta kalibreringsrader och macro-träff ≥55 % (eller explicit bekräftelse vid varning). Pool- eller korpusändring markerar kalibrering som inaktuell. Snabbrapport varnar om otestade/inaktuella ankare.
* **SSR-ankare**: Från klara körningar kan kommentarer och intervjusvar taggas som pool-ankare (ton/stil) i det aktiva konfigurationens bibliotek — gäller direkt för nya rapporter.
* **Navigering**: Toppmenyn följer devbrains.se — halvtransparent svart list med logotypen. Navigationslänkarna ligger i en rad på desktop; på liten skärm samlas de under en menyknapp.
* **Rapporter**: Full rapport (LLM-narrativ) är borttagen — bara snabbrapporten finns kvar.
* **Rapporter**: SSR-sampling för ton/stil är stratifierad per agent (max 2 texter/agent, 16 totalt) — inte längre top-by-likes. Tekniskt stycke och `report.ssr.json` loggar sampling-metod.
* **Playground**: Under Anchor-kalibrering kan reaktioner laddas från en klar körning med samma urval som rapport-SSR; valfritt klipp till 200 tecken och aktiv konfigurations SSR-temperatur vid rating.
* **Rapporter**: Slutsats-trösklar (mottagande, A/B-skillnad, rekommendation 0–100) ligger i aktiv konfiguration (`report_thresholds`) och sparas i `report.ssr.json` per rapport.
* **Konfigurationer**: Rapporttrösklar kan redigeras under fliken SSR-ankare (operatörsfält + ihopfällt avancerat). Ändringar gäller nya rapporter.
* **Konfigurationer**: Målgruppssammanfattning (takeaway-stycken) har egna trösklar under avancerat — separata från slutsats och rekommendation; kön-jämförelse delar «Tydlig skillnad».
* **Rapporter**: På rapportsidan kan operatören bedöma om slutsatsrekommendationen stämmer med hela rapporten (verdict-kalibrering).
* **Rapporter**: Stildiagrammet heter nu **Andel reaktioner per budskapsstil** och visar procent av de klassade reaktionerna — tidigare rubrik ("Genomsnittliga likes per budskapsstil") beskrev inte vad som mättes. `0 %` betyder att stilen saknas i underlaget, inte att den fick noll gehör.
* **Rapporter**: Engagemangsringen och antalet medborgare i rubriken använder samma nämnare, och underrubriken visar hur många institutionella konton som räknats bort.

## 2026-08-10

* **Återkoppling**: Ny menyflik där buggar, idéer och åsikter från hjälpchatten samlas; status kan sättas till pågår, klar eller arkiverad.
* **Hjälp**: Assistenten kan spara och läsa återkoppling (inte ändra status).
* **Hjälp**: SCB-statistik (inkl. kommunfördelning) är alltid tillgänglig i hjälpchatten; kryssrutan för populationsvikter är borttagen.
* **Budskap**: Verkstaden stödjer endast text, endast bild och bild + text; bilder cachas med SHA256 och vision-caption som delas mellan inlägg.
* **Budskap**: Miniatyrer vid val av cachad bild i verkstaden.
* **Cache**: Guide utökad med bild-cache — miniatyrer, enskild borttagning och koppling till budskap.
* **Hjälp**: Ny guide för in-app hjälpchatten (Hjälp-knappen i adminytan). Assistenten kan slå upp offentlig demografisk statistik från SCB.
* **Rapporter**: Snabbrapporten har tydligare rekommendationsblock, färre fotnoter och enklare språk utan tekniska förkortningar i operatörstexten.
* **Körningar**: Ny guide för reaktionsmodellen — stratifierat urval per rond, passiv vs engagerad, kommentarsregler och nollställning vid nytt budskag.
* **Populationer**: Personas i en population kan visas som rutnät eller lista.

## 2026-08-09

* **Rapporter**: Ny menyflik **Rapporter** med lista över alla beställda rapporter; guide för att hantera listan.
* **Rapporter**: Rapporter kan tas bort från listan och rapportsidan.
* **Rapporter**: Flera rapporter kan markeras och tas bort samtidigt.
* **Personas**: Biblioteket kan filtreras och sorteras på demografiska fält (kön, distrikt, yrke, utbildning, livssituation; sortering även på ålder).

## 2026-08-07

* **Playground**: Ny guide för att kalibrera anchors, jämföra SSR mot nyckelord och iterera prompter från konfigurationer.
* **Playground**: Temperatur (softmax) dokumenterad för anchor-kalibrering och SSR vs nyckelord.
* **Konfigurationer**: SSR-temperatur under Rapport i promptinställningar (styr skarpa rapporter).
* **Verktyg**: Konfigurationer, playground och embedding-cache samlade under menyn Verktyg; guide för att rensa cache.
* **Playground**: Flik för att testa agentverktyg (webbsök / SymPy) utan full simulering.
* **Körningar**: Agentverktyg väljs granulärt (DuckDuckGo / Wikipedia / SymPy) med eget wizardsteg och Välj alla.
* **Rapporter**: Snabbrapporten har tydligare rekommendationsblock, färre fotnoter och enklare språk utan tekniska förkortningar i operatörstexten.

## 2026-08-06

* **Jobs**: Clarified that Bakgrundsjobb updates live when status changes (no polling wording).
* **Configurations / grunddata**: Grunddata is per configuration (Promptinställningar + Grunddata tabs); removed standalone Konfiguration nav; active config drives both prompts and catalog lists.


## 2026-08-05

* **Initialization**: Created OKF manual bundle with seed guides for overview, create run, and start simulation.
* **Backfill**: Added 16 guides covering runs list, tick config, results, reports, personas, populations, messages, grunddata, jobs, and simulator demo.
* **Removal**: Dropped the paper demo simulator guide (`anvanda-simulatorn.md`) and related overview/index links after `/simulator` was removed from the product.
* **Configurations**: Added guide for managing saved prompt configurations (`hantera-konfigurationer.md`) and linked it from the index and overview.
* **Configurations**: Updated guide for multi-field prompt sets (persona/chat/messages/OASIS/report) and activating the config used by backend.
