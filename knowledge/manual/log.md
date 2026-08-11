# Manual update log

## 2026-08-11

* **Körningar**: Reaktionsmodellens stratifierade urval tar hänsyn till både distrikt och lutning när alla medlemmar har känd lutning; annars distrikt-only.
* **Populationer**: Fingeravtryck visar faktisk sammansättning (medlemmar), inte slider-mål. Recept är fryst snapshot; **Redigera recept** är borttaget — skapa ny population för annan fördelning.
* **SSR-ankare**: Publicering kräver minst åtta kalibreringsrader och macro-träff ≥55 % (eller explicit bekräftelse vid varning). Pool- eller korpusändring markerar kalibrering som inaktuell. Snabbrapport varnar om otestade/inaktuella ankare.
* **SSR-ankare**: Från klara körningar kan kommentarer och intervjusvar taggas som pool-ankare (ton/stil) i det aktiva konfigurationens bibliotek — gäller direkt för nya rapporter.
* **Navigering**: Toppmenyn följer devbrains.se — halvtransparent svart list med logotypen. Navigationslänkarna ligger i en rad på desktop; på liten skärm samlas de under en menyknapp.
* **Rapporter**: Full rapport (LLM-narrativ) är borttagen — bara snabbrapporten finns kvar.
* **Rapporter**: SSR-sampling för ton/stil är stratifierad per agent (max 2 texter/agent, 16 totalt) — inte längre top-by-likes. Tekniskt stycke och `report.ssr.json` loggar sampling-metod.
* **Playground**: Under Anchor-kalibrering kan reaktioner laddas från en klar körning med samma urval som rapport-SSR; valfritt klipp till 200 tecken och aktiv konfigurations SSR-temperatur vid rating.
* **Rapporter**: Slutsats-trösklar (mottagande, A/B-skillnad, rekommendation 0–100) ligger i aktiv konfiguration (`report_thresholds`) och sparas i `report.ssr.json` per rapport.
* **Rapporter**: På rapportsidan kan operatören bedöma om slutsatsrekommendationen stämmer med hela rapporten (verdict-kalibrering).

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
