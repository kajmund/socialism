/** Mock data ported from the Opinionssimulator mockup. */
import type {
  District,
  MessageProfile,
  NewsOption,
  Persona,
  Population,
  TimeOption,
} from "@/data/types"

// ─── Populationsprofiler ──────────────────────────────────────
export const POPULATIONS: Population[] = [
  {
    id: "norrkoping",
    tag: "Pilot — april 2026",
    name: "Norrköping realistisk",
    desc: "Demografiskt viktad spegling av Norrköpings kommun. Baserad på SCB-data, valresultat 2022 och lokal yrkesfördelning.",
    n: 1200,
    distribution: [
      { label: "Socialdemokraterna", pct: 31, color: "#B0563F" },
      { label: "Sverigedemokraterna", pct: 21, color: "#5F7A4C" },
      { label: "Moderaterna", pct: 16, color: "#2D5378" },
      { label: "Vänsterpartiet", pct: 9, color: "#C96B3A" },
      { label: "Övriga partier", pct: 14, color: "#A89D87" },
      { label: "Osäkra / soffliggare", pct: 9, color: "#6B6253" },
    ],
    stats: [
      { n: "47", l: "Medelålder" },
      { n: "42%", l: "Höginkomst" },
      { n: "18", l: "Yrkesgrupper" },
    ],
  },
  {
    id: "vagvaljare",
    tag: "Strategiskt urval",
    name: "Svängväljare",
    desc: "Personer som rapporterat att de övervägt att byta parti senaste 12 månader. Överrepresentation av S/M/SD-pendlare.",
    n: 800,
    distribution: [
      { label: "S ↔ SD-pendlare", pct: 28, color: "#B0563F" },
      { label: "S ↔ V/MP-pendlare", pct: 19, color: "#C96B3A" },
      { label: "M ↔ KD/L-pendlare", pct: 17, color: "#2D5378" },
      { label: "Tidigare osäkra", pct: 22, color: "#D8A14A" },
      { label: "Förstagångsväljare", pct: 14, color: "#A89D87" },
    ],
    stats: [
      { n: "39", l: "Medelålder" },
      { n: "61%", l: "Aktiva på sociala medier" },
      { n: "24", l: "Yrkesgrupper" },
    ],
  },
  {
    id: "opposition",
    tag: "Stresstest",
    name: "Oppositionstyngd",
    desc: "Avsiktligt skev population: 60% sympatiserar med oppositionspartier. Används för att testa hur ett budskap håller mot motvind.",
    n: 1000,
    distribution: [
      { label: "Moderaterna", pct: 28, color: "#2D5378" },
      { label: "Sverigedemokraterna", pct: 24, color: "#5F7A4C" },
      { label: "Kristdemokraterna", pct: 10, color: "#8A6E3A" },
      { label: "Liberalerna", pct: 8, color: "#7A8AAE" },
      { label: "Socialdemokraterna", pct: 18, color: "#B0563F" },
      { label: "Övriga", pct: 12, color: "#A89D87" },
    ],
    stats: [
      { n: "51", l: "Medelålder" },
      { n: "38%", l: "Höginkomst" },
      { n: "21", l: "Yrkesgrupper" },
    ],
  },
];

// ─── Personas ──────────────────────────────────────────────────
export const PERSONAS: Persona[] = [
  {
    name: "Margareta Hellström",
    age: 67,
    occupation: "Pensionerad undersköterska",
    district: "Hageby",
    party: "Socialdemokraterna",
    leaning: "Stadigt vänster, lokalt förankrad",
    initials: "MH",
    color: "#B0563F",
    traits: ["Omtänksam", "Vardagsnära", "Skeptisk till floskler", "Engagerad i PRO"],
    style: "Berättar gärna anekdoter från arbetet på Vrinnevisjukhuset. Använder uttryck som 'förr i tiden'. Sällan ironisk.",
    quote: "Jag tycker det är fint att de tänker på oss gamla, men jag vill se vad det betyder i pengar — inte bara fina ord.",
    knows: ["PRO Hageby", "Väntetider Vrinnevi", "Buss 11 till Centrum", "Skolnedläggning Ektorpsskolan"],
    reactA: { tone: "Tveksam", text: "Vackra ord. Men jag har hört det här förut. ‘Trygghet på äldre dar’ — vad innebär det egentligen?", action: "Scrollar vidare" },
    reactB: { tone: "Positiv", text: "Äntligen någon som nämner Vrinnevi vid namn. 200 nya undersöterskor i Norrköping — det är konkret.", action: "Delar i PRO-gruppen" }
  },
  {
    name: "Jonas Lundqvist",
    age: 34,
    occupation: "Lagerarbetare, Postnord",
    district: "Navestad",
    party: "Sverigedemokraterna",
    leaning: "Konservativ, trött på etablissemang",
    initials: "JL",
    color: "#5F7A4C",
    traits: ["Rakt på", "Sarkastisk", "Misstänksam", "Bilintresserad"],
    style: "Korta meningar, gärna med utropstecken. Använder 'man' istället för 'jag'. Lägger upp memes.",
    quote: "Snacka går ju lätt. Visa pengarna då. Eller är det val nästa år?",
    knows: ["A-traktorsfrågan", "Postnords lager i Händelö", "Bilträffar vid Ingelsta", "Bostadskön i Navestad"],
    reactA: { tone: "Avvisande", text: "Vackra principer. Försök köra A-traktor på principer.", action: "Ignorerar" },
    reactB: { tone: "Sval men lyssnande", text: "OK, 200 stycken. Konkret åtminstone. Får vi se om de levererar.", action: "Gillar inlägget" }
  },
  {
    name: "Aisha Karim",
    age: 28,
    occupation: "Lågstadielärare, Ektorpsskolan",
    district: "Klockaretorpet",
    party: "Vänsterpartiet",
    leaning: "Progressiv, jämlikhetsfokus",
    initials: "AK",
    color: "#C96B3A",
    traits: ["Idealistisk", "Påläst", "Empatisk", "Aktiv i lärarförbundet"],
    style: "Resonerande, ställer motfrågor. Hänvisar gärna till forskning. Skriver långa inlägg.",
    quote: "Det här låter bra på pappret, men hur ska det finansieras? Vem betalar?",
    knows: ["Lärarbristen i kommunen", "Ektorpsskolans renovering", "Lärarförbundet lokalt", "Närheten Klockaretorpet–Hageby"],
    reactA: { tone: "Försiktigt positiv", text: "Ett principiellt viktigt utspel. Men jag saknar konkretion — hur många tjänster, vilken finansiering?", action: "Kommenterar med frågor" },
    reactB: { tone: "Skeptisk", text: "Konkret, men reduktivt. Äldreomsorg är mer än bemanning — var är helhetssynen?", action: "Skriver replikinlägg" }
  },
  {
    name: "Bengt Andersson",
    age: 58,
    occupation: "Snickare, eget företag",
    district: "Lindö",
    party: "Moderaterna",
    leaning: "Borgerlig, lågskattevän",
    initials: "BA",
    color: "#2D5378",
    traits: ["Pragmatisk", "Otålig", "Egenföretagare", "Skeptisk till regleringar"],
    style: "Talar om praktiska konsekvenser. Använder 'i verkligheten'. Avskyr svammel.",
    quote: "Vem ska göra jobbet då? Inte politikerna i alla fall. Vi som driver företag får sköta det själva som vanligt.",
    knows: ["Företagarna Norrköping", "Lindö båtklubb", "Bygglovsärenden i kommunen", "Arbetskraftsbrist i hantverksyrken"],
    reactA: { tone: "Avvisande", text: "Solidaritet, javisst. Vem ska betala Ökade arbetsgivaravgifter igen?", action: "Scrollar förbi" },
    reactB: { tone: "Motvilligt läser", text: "200 undersöterskor. OK. Vem ska utbilda dem? Och varifrån ska pengarna komma?", action: "Läser kommentarerna" }
  },
  {
    name: "Linnea Persson",
    age: 22,
    occupation: "Student, Linköpings universitet",
    district: "Centrum (Saltängen)",
    party: "Miljöpartiet",
    leaning: "Grön, globalistisk",
    initials: "LP",
    color: "#5F7A4C",
    traits: ["Engagerad", "Hoppfull", "Klimatfokus", "Aktiv på TikTok"],
    style: "Uttrycksfull, känslodriven. Använder emojis sparsamt. Delar gärna vidare.",
    quote: "Äntligen någon som vågar prata om det! Men varför nämner ingen klimatet i sammanhanget?",
    knows: ["Pendling LiU–Norrköping", "Klimatdebatten lokalt", "Strömmens utbyggnad", "Cykelinfrastruktur i Centrum"],
    reactA: { tone: "Värmd", text: "Solidaritet, jaaa! Välfärden är en rättighet. Men hur kopplas det till grön omställning?", action: "Delar med kommentar" },
    reactB: { tone: "Ljum", text: "Konkret är bra men känns smått. Var är den större visionen för vården?", action: "Läser men delar inte" }
  },
  {
    name: "Hassan Yusuf",
    age: 45,
    occupation: "Taxichaufför, Norrköping Taxi",
    district: "Berga",
    party: "Socialdemokraterna",
    leaning: "Mittenvänster, familjefokus",
    initials: "HY",
    color: "#B0563F",
    traits: ["Jordnära", "Familjeman", "Pratglad", "Trött på höga drivmedelspriser"],
    style: "Anekdotiskt, refererar till kunder och samtal i bilen. Vänligt men direkt.",
    quote: "I går hade jag en kund som väntat sex timmar på akuten. Sex timmar. Det är där vi är nu.",
    knows: ["Akutmottagningen Vrinnevi", "Bensinpriser Berga", "Taxi-marknaden lokalt", "Hur Berga och Navestad förändrats"],
    reactA: { tone: "Trött", text: "‘Sverige förtjänar trygghet’ — mina kunder pratar om akutväntetider, inte slogans.", action: "Läser, skrollar" },
    reactB: { tone: "Igenkännande", text: "Det här är precis vad jag hör i bilen varje dag. Hassan-anekdoten kunde varit min kund.", action: "Delar i tre WhatsApp-grupper" }
  },
  {
    name: "Eva Sjögren",
    age: 52,
    occupation: "Sjuksköterska, Vrinnevisjukhuset",
    district: "Smedby",
    party: "Socialdemokraterna ↔ Vänsterpartiet",
    leaning: "Vänster, men trött",
    initials: "ES",
    color: "#B0563F",
    traits: ["Erfaren", "Cynisk underton", "Faktasäker", "Arbetar nattskift"],
    style: "Saklig, faktabaserad. Lyfter fram detaljer som lekmän missar. Sällan svartvit.",
    quote: "Vi har hört det här i 15 år. Vad är skillnaden den här gången? Konkret?",
    knows: ["Bemanning Vrinnevi", "Vårdförbundet lokalt", "Nattskiftens villkor", "Smedby–Vrinnevi pendling"],
    reactA: { tone: "Cynisk", text: "15:e gången jag läser den meningen. Ingen substans. *suck*", action: "Ignorerar helt" },
    reactB: { tone: "Sval men öppen", text: "OK — 200 undersöterskor första året. Var länge satt jag i den lokala bemanningsgruppen. Det skulle synas.", action: "Citerar med kommentar" }
  },
  {
    name: "Robin Söderberg",
    age: 19,
    occupation: "Gymnasieelev, Ebersteinska gymnasiet",
    district: "Skarphagen",
    party: "Osäker / förstagångsväljare",
    leaning: "Lyssnande, opåverkad ännu",
    initials: "RS",
    color: "#D8A14A",
    traits: ["Bilintresserad (A-traktor)", "Kompisorienterad", "Praktisk", "Skeptisk till politiker generellt"],
    style: "Korthugget, slang. Reagerar mer än kommenterar. Delar i grupper.",
    quote: "Lugn liksom. Bara de inte börjar med A-traktorerna igen.",
    knows: ["A-traktorsregler", "Skarphagens IP", "McDonalds Ingelsta", "Ebersteinska skolmiljö"],
    reactA: { tone: "Likgiltig", text: "Bruh. Inte ens i närheten av något som angår mig.", action: "Stannar 1 sekund" },
    reactB: { tone: "Stannar kort", text: "OK 200 jobb. För typ såna som min mormor. Cool.", action: "Tittar på men delar inte" }
  },
];

// ─── A/B-jämförelsedata på resultatsidan ───────────────────────
export const MESSAGE_PROFILES: { a: MessageProfile; b: MessageProfile } = {
  a: {
    label: "Budskap A",
    style: "Abstrakt, princip-driven",
    color: "#1E3A55",
    excerpt: "Vi måste investera i äldreomsorgen. Sverige förtjänar trygghet på äldre dar och en värdig omsorg för alla.",
    avgEngagement: 32,
    reach: 18400,
    sharedBy: 412,
    dominantTopic: "Skatter & finansiering",
    characteristicQuote: "‘Vackra ord. Men hur många tjänster, vilken finansiering?’",
    characteristicWho: "Aisha Karim, lärare",
    audience: "Akademiker, klimatväljare, principstyrda",
    topPersonas: [
      { who: "Aisha Karim", initials: "AK", color: "#C96B3A", v: 64 },
      { who: "Linnea Persson", initials: "LP", color: "#5F7A4C", v: 48 },
      { who: "Hassan Yusuf", initials: "HY", color: "#B0563F", v: 51 },
    ],
    drift: [82, 68, 54, 42, 35, 30, 28],
    driftSecondary: { name: "Skatter & finansiering", values: [10, 18, 28, 38, 44, 48, 50], color: "#C96B3A" },
  },
  b: {
    label: "Budskap B",
    style: "Konkret, anekdotisk, lokal",
    color: "#C96B3A",
    excerpt: "Eva på Vrinnevi jobbar tredje natten i rad. Margareta i Hageby har väntat två veckor. Vi tillsätter 200 nya undersöterskor.",
    avgEngagement: 46,
    reach: 28600,
    sharedBy: 891,
    dominantTopic: "Vrinnevisjukhuset & personal",
    characteristicQuote: "‘Det här är precis vad jag hör i bilen varje dag.’",
    characteristicWho: "Hassan Yusuf, taxichaufför",
    audience: "Äldre, arbetarklass, lokalpatrioter",
    topPersonas: [
      { who: "Margareta Hellström", initials: "MH", color: "#B0563F", v: 71 },
      { who: "Hassan Yusuf", initials: "HY", color: "#B0563F", v: 68 },
      { who: "Eva Sjögren", initials: "ES", color: "#B0563F", v: 62 },
    ],
    drift: [82, 71, 58, 44, 39, 36, 35],
    driftSecondary: { name: "Vrinnevisjukhuset specifikt", values: [4, 8, 14, 19, 22, 22, 21], color: "#5F7A4C" },
  },
};

// ─── Vad agenterna 'vet' om Norrköping (transparens) ───────────
export const LOCAL_CONTEXT = {
  summary: "Varje agent grundas i en strukturerad kunskapsfil om Norrköping innan simuleringen körs. Modellen 'lever' inte i staden — den får faktabladet som kontext.",
  layers: [
    { lbl: "Geografi & demografi", val: "Stadsdelarnas läge, åldersstruktur, hushållstyper, närhet till varandra (SCB + kommunens statistik 2024)." },
    { lbl: "Lokala konflikter", val: "Vrinnevisjukhusets bemanning, A-traktorsfrågan, skolnedläggning Ektorpsskolan, hamnutbyggnaden i Pampas, vindkraften." },
    { lbl: "Mediekanaler", val: "NT, Folkbladet, Östgöta Correspondenten, lokala Facebook-grupper per stadsdel (Hageby, Lindö m.fl.)." },
    { lbl: "Sociala kartan", val: "Vilka områden som upplevs som 'vi' vs 'dom' — t.ex. Lindö ↔ Hageby, Centrum ↔ förorter. Inte bara avstånd utan identitet." },
    { lbl: "Det modellen INTE vet", val: "Senaste veckans nyheter, oannonserade beslut, privata händelser, samtal som inte når digitala medier." },
  ],
};

// ─── Stadsdelar för heatmap ────────────────────────────────────
// engA / engB = engagemang (%) i stadsdelen för respektive budskap
// pop = ungefärlig andel av populationen som bor där
export const DISTRICTS: District[] = [
  { id: "hageby",        name: "Hageby",         pop: 9,  engA: 38, engB: 74, persona: "MH" },
  { id: "navestad",      name: "Navestad",       pop: 7,  engA: 14, engB: 41, persona: "JL" },
  { id: "klockaretorpet",name: "Klockaretorpet", pop: 6,  engA: 61, engB: 52, persona: "AK" },
  { id: "lindo",         name: "Lindö",          pop: 8,  engA: 18, engB: 36, persona: "BA" },
  { id: "centrum",       name: "Centrum",        pop: 12, engA: 56, engB: 49, persona: "LP" },
  { id: "berga",         name: "Berga",          pop: 8,  engA: 44, engB: 69, persona: "HY" },
  { id: "smedby",        name: "Smedby",         pop: 6,  engA: 31, engB: 58, persona: "ES" },
  { id: "skarphagen",    name: "Skarphagen",     pop: 5,  engA: 12, engB: 28, persona: "RS" },
  { id: "vilbergen",     name: "Vilbergen",      pop: 7,  engA: 34, engB: 61, persona: null },
  { id: "ektorp",        name: "Ektorp",         pop: 8,  engA: 41, engB: 55, persona: null },
  { id: "eneby",         name: "Eneby",          pop: 6,  engA: 39, engB: 47, persona: null },
  { id: "saltangen",     name: "Saltängen",      pop: 5,  engA: 52, engB: 44, persona: null },
  { id: "oxelbergen",    name: "Oxelbergen",     pop: 5,  engA: 27, engB: 51, persona: null },
  { id: "jursla",        name: "Jursla",         pop: 4,  engA: 22, engB: 38, persona: null },
  { id: "krokek",        name: "Krokek",         pop: 4,  engA: 19, engB: 33, persona: null },
];

// ─── Tidsperiod / nyhets-injektioner ──────────────────────────
export const TIME_OPTIONS: TimeOption[] = [
  { id: "12h", label: "12 timmar", desc: "Tidig kvällsbevakning — primär målgrupp ser inlägget först" },
  { id: "24h", label: "24 timmar", desc: "Standardperiod — fångar både morgon- och kvällstoppen" },
  { id: "48h", label: "48 timmar", desc: "Längre eko — inkluderar reaktion på reaktion" },
  { id: "7d",  label: "7 dygn",    desc: "Långsam diffusion — användbart för opinionsbildande budskap" },
];

export const NEWS_OPTIONS: NewsOption[] = [
  { id: "none", label: "Ingen nyhet", desc: "Rent budskapstest, ingen extern störning" },
  { id: "competing", label: "Konkurrerande utspel", desc: "Annat parti gör ett liknande utspel halvvägs in i perioden" },
  { id: "scandal", label: "Negativ nyhet om partiet", desc: "Tidigare opublicerad sakfråga blir granskad i media" },
  { id: "local", label: "Lokal händelse (Norrköping)", desc: "Trafikolycka, skolnedläggning eller motsvarande lokal kris" },
];

// ─── Förinspelat resultat ─────────────────────────────────────
export const RESULTS = {
  winner: "B",
  winnerMargin: 14,    // procentenheter engagemang
  winnerStyle: "Konkret, anekdotisk, lokalt förankrad",
  loserStyle: "Abstrakt, princip-driven, partiretorik",

  // engagemang per persona (procent av påverkade som engagerade sig)
  engagement: [
    { who: "Margareta", a: 42, b: 71 },
    { who: "Jonas",     a: 8,  b: 23 },
    { who: "Aisha",     a: 64, b: 58 },
    { who: "Bengt",     a: 12, b: 31 },
    { who: "Linnea",    a: 48, b: 39 },
    { who: "Hassan",    a: 51, b: 68 },
    { who: "Eva",       a: 29, b: 62 },
    { who: "Robin",     a: 6,  b: 18 },
  ],

  // ämnesdrift över tid (% av konversationen som handlar om varje ämne)
  drift: {
    hours: [0, 4, 8, 12, 16, 20, 24],
    topics: [
      { name: "Äldreomsorg (kärnbudskap)", color: "#1E3A55", values: [82, 71, 58, 44, 39, 36, 35] },
      { name: "Skatter & finansiering",     color: "#C96B3A", values: [8,  14, 19, 23, 24, 25, 25] },
      { name: "Vrinnevisjukhuset specifikt", color: "#5F7A4C", values: [4,  8,  14, 19, 22, 22, 21] },
      { name: "Personal & arbetsvillkor",   color: "#D8A14A", values: [6,  7,  9,  14, 15, 17, 19] },
    ],
  },

  // opinionsledare
  leaders: [
    { name: "Hassan Yusuf", role: "Taxichaufför, Berga", reach: 312, desc: "Spred budskap B i WhatsApp-grupper; citerades i lokala Facebook-trådar." },
    { name: "Eva Sjögren",  role: "Sjuksköterska, Smedby", reach: 248, desc: "Trovärdighetshöjare. Hennes engagemang konverterade osäkra i populationen." },
    { name: "Margareta Hellström", role: "Pensionerad, Hageby", reach: 187, desc: "Drev konversationen i äldre kohorter och PRO-nätverk." },
  ],

  // Sammanfattande slutsatser
  notes: [
    "Budskap B vinner med 14 procentenheters marginal i engagemang, främst genom överlägsen prestation i ålderskohorten 55+.",
    "Konkret namngivning av Vrinnevisjukhuset triggade lokal identifikation — 21% av konversationen om B nämnde sjukhuset spontant vid timme 24.",
    "Budskap A presterade bättre hos akademiker (Aisha, Linnea) men de utgör för liten andel av populationen för att kompensera.",
    "Drift mot 'finansiering' efter timme 12 är konsistent — rekommendation: förbered svar på finansieringsfrågan i uppföljningsmaterial.",
    "Hassan Yusufs roll som opinionsledare överraskade — taxichaufförer fungerar som informationsmäklare i Berga och Navestad.",
  ],
};
