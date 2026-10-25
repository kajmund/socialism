# SWE: Sweycoins och en självlärande researchmotor

**Strategi och experimentplan — 25 oktober 2026**  
**Status:** Idé- och experimentunderlag, inte ett beslut om produktionsarkitektur.

## 1. Vision

Socialism Work Engine (SWE) ska kunna lösa komplexa researchfrågor snabbt, resurssnålt och med spårbar kvalitet. Motorn ska inte bara exekvera ett på förhand bestämt workflow, utan kunna pröva flera lösningsvägar, omfördela resurser och över tid lära sig vilka strategier som fungerar för olika typer av problem.

Det långsiktiga stresstestet är ett mycket stort, fast dokumentkorpus — exempelvis de så kallade Epstein-filerna — som en demonstration av effektiv kunskapsextraktion och kunskapsutforskning, inte som ett påstående om innehållet i dokumenten.

## 2. Utgångsläge

- SWE är skriven i Rust, använder Overgraph och stöder avbrott och återupptagning.
- Exekveringsvägar kan vara deterministiska regler, JEV-baserad analys och narrativ LLM.
- Research kan använda asynkrona JEV-anrop över chunkad text, SSR-ankare, retrieval, graftraversering och cachning.
- Golden Questions med facit ger en testbänk för verifierbar utvärdering.
- Målet är att undvika onödiga modell- och källanrop, särskilt vid stora korpusar.

## 3. Centrala idéer från diskussionen

### 3.1 Spekulativ exekvering

Starta flera alternativa vägar parallellt när det är oklart vilken som är bäst. En billig deterministisk väg kan misslyckas snabbt; en JEV-väg kan komma långt på en liten budget; en LLM-väg kan hitta helhetsrelationer som chunkad analys missar.

**Viktigt:** Snabbast är inte samma sak som korrekt. Ett svar måste uppfylla explicita evidens- och kvalitetsvillkor innan det kan användas som verifierat resultat.

### 3.2 Levande, versionerade svar

Alla vägar får bidra till ett aggregerat svar. Tidiga svar kan publiceras som preliminära och senare kompletteras, motsägas eller revideras. Resultat ska vara versionerade och ha provenance. Nedströms steg ärver preliminärhet från de indata de faktiskt använder. Vid ändringar markeras beroende resultat inaktuella och relevanta delsteg körs om.

Skilj på **färdigställandegrad** (preliminär/fastställd för en körning), **aktualitet** (aktuell/inaktuell) och **evidensstyrka**. Ett fastställt svar är inte garanterat evigt sant.

### 3.3 Budgeterad spekulation

Att låta ett steg med 2 500 JEV-anrop köras fullt ut på osäkra indata kan bli dyrt. SWE bör kunna ge en liten initial budget, mäta framsteg och tilldela mer när det finns skäl. Spekulationsbudget och totalbudget är separata. Återanvänd cachade delresultat om deras beroenden fortfarande är giltiga.

### 3.4 Sweycoins

**Sweycoins** är SWE:s interna kostnadsenhet. De kan debiteras för JEV-anrop, LLM-tokens/anrop, Overgraph-sökning, CPU-arbete och andra resurser. Inledande priser är experimentella, exempelvis JEV = 1, LLM-anrop = 10 och grafuppslag = 0,01 Sweycoins; de ska kalibreras mot uppmätt resursåtgång. Väggklockstid och svarskvalitet mäts separat.

### 3.5 Självlärande budgetfördelning

En liten policy-modell kan använda frågeembedding, uppgiftstyp, historiska utfall, hittillsvarande kostnad och verifierbara framsteg för att bedöma den förväntade nyttan av ytterligare budget på en viss väg. Börja med regler och loggning; jämför därefter regression/gradient boosting och contextual bandits. En möjlig fråga för policyn är: *Hur mycket förbättras sannolikheten för ett verifierat svar om denna väg får ytterligare 10 Sweycoins?*

### 3.6 Virtuella portföljer och modellmarknad

Flera investerarstrategier får var sin virtuell portfölj och kan investera budget i egna eller andras exekveringsstrategier. En modell kan exempelvis känna igen en frågetyp och delegera till en annan som är bättre på att välja researchväg. Belöningar betalas för verifierade resultat, särskilt svåra frågor, men kostnaden dras av. Portföljvärde blir en tränings- och jämförelsesignal, **inte** en obegränsad verklig budget.

## 4. Principer för ekonomin

1. **Bevarande:** Delegering flyttar budget; den skapar inte nya Sweycoins. Belöningar i gymmet bokförs separat som simulerad intäkt och ger inte automatiskt rätt att förbruka fler verkliga resurser.
2. **Verifiering:** Belöning baseras på facit och evidens, inte modellens egen självsäkerhet.
3. **Svårighetsviktning:** Svårare uppgifter kan ge större belöning, men svårighet ska bestämmas i förväg från testdata eller oberoende baslinjer, inte efter modellens egen förbrukning.
4. **Jämförbarhet:** Alla strategier utvärderas på samma eller statistiskt balanserade frågor, med held-out testmängd.
5. **Ingen dubbel belöning:** En gemensam belöning fördelas mellan investerare och utförare enligt fast regel; den multipliceras inte i delegationskedjan.
6. **Skydd mot loopar:** Delegeringar har maxdjup, tidsgräns, budgettak och cykeldetektering.
7. **Konkurs utan minnesförlust:** Underpresterande strategier pausas eller får lägre experimentandel; deras historik bevaras.
8. **Separata mätvärden:** Kvalitet, kostnad, latens och evidenstäckning redovisas var för sig, även när en sammanvägd belöning används.

## 5. Föreslagen minimal arkitektur

**SWE Rust runtime:** Schemaläggning, parallella grenar, budgetreservation, avbrott/resume, cancellation och versionsberoenden.

**Overgraph:** Persistens för frågefeatures, workflow- och delresultat, provenance, kostnadshändelser, strategiutfall och cache med tydlig isolering mellan experimentella och verifierade data.

**Budget ledger:** Append-only händelser för `reserve`, `spend`, `refund`, `delegate` och `reward`. Atomisk debitering och idempotensnycklar för att undvika dubbeldebitering vid resume/retry.

**Strategy interface:** En strategi får ett tillstånd och returnerar ett budgetförslag: fortsätt, pausa, avbryt, delegera eller publicera preliminärt resultat. Runtime verkställer säkerhets- och kostnadstak.

**Evaluator:** Jämför svar mot golden-facit och evidenskrav. Mäter fullständighet, korrekthet, kostnad, latens och stabilitet efter revisioner.

**Policy trainer:** Tränas offline på körloggar. Policyversion och träningsdata-version loggas för reproducerbarhet.

## 6. Första experimentet: minsta användbara gym

**Syfte:** Testa om spekulativ budgetfördelning ger högre verifierad svarskvalitet per Sweycoin än en enkel baslinje.

**Material:** Ett fryst urval Golden Questions med facit, grupperade efter svårighetsgrad och frågetyp. Börja smått och reservera separata frågor för sluttest.

**Armar:**

- A: Sekventiell prioritet — deterministisk → JEV → LLM.
- B: Parallell körning med lika startbudget och deterministisk fortsättningsregel.
- C: Parallell körning med adaptiv budget baserad på observerade framsteg.
- D (senare): Liten inlärd policy.
- E (ännu senare): Flera portföljer med begränsad delegering mellan strategier.

**Körprotokoll:**

1. Tilldela varje fråga ett totalt resurstak och samma datatillgång.
2. Starta tillåtna grenar med liten initial budget.
3. Logga kostnad och verifierbara delresultat efter varje budgetkvantum.
4. Stoppa uppenbart misslyckade vägar; ge mer budget till lovande vägar inom taket.
5. Publicera eventuellt preliminära svar, men använd bara verifierade svar för huvudpoängen.
6. Bedöm slutresultat mot facit och spara komplett körspår.
7. Upprepa över frågor och slumpfrön; jämför kvalitet–kostnad-kurvor, latens och feltyper.

**Mätvärden:** Accuracy/facitmatch, evidensfullständighet, kostnad per korrekt svar, P50/P95-latens, andel frågor lösta inom budget, antal onödiga anrop, antal revisioner och återanvänd cache.

**Exempel på virtuell belöning:** `reward = difficulty_weight × verified_quality × base_payout − sweycoins_spent`. Detta är endast en startformel. Rapportera även de separata komponenterna; annars kan en sammanvägd poäng dölja regressionsfel.

## 7. Viktiga risker och kontrollpunkter

- **Tidiga framsteg kan vilseleda:** Ett spår kan se lovande ut men aldrig nå korrekt slutsats. Mät fullständiga utfall, inte bara progress-score.
- **Träningsbias:** Historiska loggar innehåller främst de vägar som tidigare fick budget. Kontrollerad exploration behövs för att jämföra alternativ rättvist.
- **Reward hacking:** Belöningsfunktionen kan exploateras. Håll facit åtskilt från strategierna och utvärdera på okända frågor.
- **Kostnadsexplosion:** Globala och per-gren-budgettak gäller alltid, även vid delegation och retries.
- **Spekulativa bieffekter:** Externa, irreversibla handlingar får inte köras från preliminära resultat utan explicit commit-policy.
- **Motsägande resultat:** Behåll båda evidenskedjorna och märk konflikten; skriv inte över tidigare svar tyst.
- **Överanpassning:** Ett gym med få frågor räcker inte för att påstå att en policy generaliserar.

## 8. Föreslagen genomförandeordning

**Fas 0 — Instrumentera:** Kostnadsledger, Sweycoin-tariffer, reproducerbara körloggar och kvalitetsevaluator.

**Fas 1 — Deterministisk budget:** Små initiala anslag, fail-fast, globala tak och cacheåteranvändning. Ingen tränad modell.

**Fas 2 — Levande svar:** Versionshantering, preliminärhetspropagering och selektiv omkörning. Börja med read-only researchsteg.

**Fas 3 — Lärande:** Träna en liten policy offline, kör i shadow mode och jämför med fas 1 på held-out frågor.

**Fas 4 — Marknadsgym:** Virtuella portföljer, belöning för svåra verifierade frågor och begränsad delegering. Jämför mot central budgetfördelare.

**Fas 5 — Skalning:** Större och mer heterogena korpusar, gradvis mot Epstein-filerna som stresstest för ingestion, retrieval, provenance, cache och research.

## 9. Vad som är beslutat respektive öppet

**Gemensam riktning:** Experimentera med Sweycoins, budgeterad spekulation, levande resultat och inlärd strategioptimering i SWE:s researchmotor.

**Öppet:** Prissättning, budgetkvantum, kvalitetsmått, svårighetsvikter, modellfamiljer, policy för preliminära beroenden, belöningsfördelning vid delegation och exakt Overgraph-schema.

**Rekommenderat första kodsteg:** Bygg en append-only Sweycoin-ledger och ett reproducerbart benchmark som jämför sekventiell exekvering mot parallell exekvering med liten startbudget. Lägg inte till portföljmarknaden förrän detta kan mätas.

---

**Kärnhypotes:** SWE kan leverera fler verifierat korrekta researchsvar per resursenhet genom att spekulativt utforska flera vägar, lära av tidigare utfall och omfördela budget — utan att kompromissa med spårbarhet och kostnadstak.

## 10. Reinforcement learning: hybridträning i SWE Gym

**Vald experimentriktning:** Samla erfarenheter efter varje Golden Question, uppdatera investerarmodellernas parametrar i minibatcher och utvärdera varje generation på separata frågor. Uppdateringsfrekvensen är en hyperparameter, inte en fast regel.

### Tre jämförbara träningsregimer

- **Online:** Uppdatera efter varje fråga. Snabb anpassning, men högre risk för brus och instabilitet.
- **Batch:** Kör en fryst policy genom exempelvis 200 frågor och uppdatera därefter. Stabilare jämförelse men långsammare anpassning.
- **Hybrid (förstahandsval):** Logga varje fråga, uppdatera exempelvis var 20:e fråga och genomför en generationsutvärdering efter 200 frågor. Siffrorna är experimentparametrar, inte optimerade värden.

### Körning och datadisciplin

1. Dela Golden Questions i **träning**, **validering** och ett **orört sluttest**; gruppera närbesläktade frågor och källdokument så att facit eller nära dubbletter inte läcker mellan delmängder.
2. För varje beslut, logga frågefeatures, policyversion, tillstånd, tillgängliga handlingar, vald handling, budget, observerat utfall och sannolikheten för vald handling om policyn är stokastisk.
3. Kör SWE med hårda Sweycoin-tak; räkna verkliga kostnader och facitbaserad belöning. Spara delresultat och evidens i Overgraph.
4. Samla erfarenheter kontinuerligt; gör policyuppdateringar efter ett konfigurerbart antal frågor, exempelvis 1, 20 eller 200. Frys policyn under varje utvärderingsblock.
5. Jämför generationer på valideringsfrågor. Använd sluttestet sparsamt, för en slutlig opartisk jämförelse, inte för att välja hyperparametrar.
6. Rapportera verifierad kvalitet per Sweycoin, lösta frågor inom budget, latens och osäkerhet; jämför alltid med en deterministisk budgetbaslinje.

### Vad som tränas

Första versionen tränar **budget- och routingpolicyn**, inte JEV eller den narrativa språkmodellen. Börja med contextual bandits för ett enstaka budgetbeslut. Om policyn ska göra flera beroende beslut under en och samma researchkörning (fortsätt, pausa, delegera, avbryt) kan experimentet utökas till sekventiell RL.

**Viktiga reservationer:** Återspelning av cachade körningar är billig men visar inte säkert utfallet av handlingar som aldrig provades. Sådana kontrafaktiska val kräver kontrollerad exploration, nya riktiga körningar eller en validerad simulator. Portföljernas virtuella avkastning får inte kringgå verkliga resurstak. Undersök även om olika investerarstrategier gynnas av olika uppdateringsintervall, men utvärdera dem under samma jämförbara förutsättningar.

## 11. Minimal Sweycoin Ledger (första implementationen)

**Syfte:** Mät, reservera och bokför budget i SWE:s Rust-runtime. Detta är en experimentell infrastrukturkomponent; inga lärande modeller krävs.

### Modell

- `run_id`: researchkörning.
- `account_id`: budgetkonto (rotkörning eller delegerad gren).
- `event_id`: unik händelseidentitet.
- `idempotency_key`: stabil nyckel för retries/resume.
- `kind`: `allocate | reserve | spend | release | transfer | reward`.
- `amount_milli`: positivt heltal i tusendels Sweycoin; undvik flyttal.
- `operation_id`: den JEV-, LLM-, retrieval- eller CPU-operation som debiteras.
- `timestamp`, `metadata`: revisionsspår och tarifferingsversion.

**Balans:** `available = allocated + incoming_transfers - outgoing_transfers - spent - reserved`. En reservation flyttar belopp från tillgängligt till reserverat. `spend` kan konsumera en reservation; `release` återför outnyttjad reservation. Alla överföringar ska vara atomiska och balanserade. `reward` bokförs **endast** i gymmets separata virtuella poängkonto och påverkar aldrig tillgänglig exekveringsbudget.

### Exempel

En researchkörning får 100 Sweycoins. JEV-grenen reserverar 20, spenderar 12 och återlämnar 8. LLM-grenen reserverar 30, spenderar 25 och återlämnar 5. Verklig förbrukning är 37 och 63 återstår tillgängliga (förutsatt inga andra reservationer eller utgifter). En verifierad lösning kan samtidigt ge exempelvis 80 virtuella belöningscoins, utan att öka de 63 som får spenderas.

### Rust-API (förslag)

```rust
trait SweycoinLedger {
    fn reserve(&self, run: RunId, account: AccountId, amount_milli: u64, key: &str) -> Result<ReservationId>;
    fn settle(&self, reservation: ReservationId, spent_milli: u64, key: &str) -> Result<()>;
    fn transfer(&self, from: AccountId, to: AccountId, amount_milli: u64, key: &str) -> Result<()>;
    fn balance(&self, account: AccountId) -> Result<Balance>;
}
```

`settle` debiterar faktisk kostnad och frigör återstoden atomiskt. Separat gym-API bokför `reward`. Börja med en append-only eventlogg och en materialiserad balans per konto; använd samma transaktionsgräns för reservation och debitering. Persistensbackend väljs efter befintliga SWE-förutsättningar, utan att anta att Overgraph i sig erbjuder transaktioner.

### Acceptanskriterier

1. Parallella grenar kan aldrig spendera mer än körningens hårda tak.
2. Retry och resume med samma idempotency key debiterar exakt en gång.
3. Avbruten gren frigör ej spenderad reservation.
4. Delegering bevarar total exekveringsbudget och kan inte skapa cirkulär obegränsad kredit.
5. Ledgern kan återspelas deterministiskt och revideras per körning, gren och operation.
6. Virtuell reward kan aldrig användas för att kringgå resurstaket.
7. Tester omfattar parallella reservationer, krascher mellan steg, dubbla events och negativa balansförsök.

**Första experiment:** Instrumentera JEV-anrop med en fast testtariff och verifiera att 100 parallella anrop under ett tak på 20 Sweycoins inte kan debitera mer än taket. Lägg därefter till LLM-tokens och Overgraph-uppslag.
