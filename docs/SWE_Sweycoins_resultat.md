# SWE: Sweycoins — resultat från PoC-experimentet

**Komplement till [SWE_Sweycoins_strategi.md](SWE_Sweycoins_strategi.md).**
**Status:** uppmätta resultat och lärdomar från experiment-craten `crates/swe-gym/`
(mergad i PR #435). Alla siffror är pinnade i cratens tester.

## 1. Vad som byggdes

Ett fristående experiment (egen AGENTS.md) med hela kedjan från strategidokumentet
i miniatyr: append-only Sweycoin-ledger, metrad harness ovanpå swe-native-kärnan,
armar A–H, två inlärda policies, TD(0)-Sarsa, och en riktig bench över projektets
egen korpus. Live-anrop (JEV, Cerebras, OpenAI-inbäddningar) är env-gatade
engångskörningar; allt annat — inklusive CI — är offline och deterministiskt.

## 2. Uppmätta resultat

### 2.1 Syntetiska världar (scriptade providers)

- **Armjämförelse, fryst bench:** A (sekventiell) löser den lätta frågan för 6
  Sweycoins, B (parallell, lika budget) för 16 (spekulationsskatt), C (adaptiv)
  för 6; på den svåra frågan är A och B olösta medan C löser den för 20 — hela
  skillnaden är en facit-fri signal (konfidens nära tröskeln) och en omordningsregel.
- **Banditen (D, ett budgetbeslut):** lär sig C:s eskalering ur data, utan facit.
  I den brusiga världen hittar den en *egen* punkt på kvalitet–kostnad-fronten:
  243/500 lösta mot C:s 331, men **bäst kvalitet per Sweycoin** (0.0337 mot 0.0311).
- **TD (G, sekventiellt beslut):** konvergerar till exakt C i den ostrukturerade
  världen (331/500, identisk spend) — C är optimum för den tillgängliga signalen.
  I den strukturerade världen (evidens klustrad i första halvan) **slår TD C på
  båda axlarna** (337/500 och billigare), genom att lära sig regiongränsen.
- **Slutsats:** adaptivitet betalar sig bara där signalerna bär information, och
  RL-maskineriet hittar optimum av det man matar in.

### 2.2 Riktig bench (projektets korpus, riktig JEV, riktigt gold)

Fem guldfrågor (auto-renewal, notice-period, liability-cap, confidentiality,
liability-secrecy-carveout), 2019 frysta JEV-svar:

- **Riktig JEV hittar 100 % av guldet, 0 missar, på alla fem frågorna.**
  Extra fynd följer frågans specificitet: carveout 0, liability-cap 17.
- **Scanningsfronten** (chunks skannade tills all evidens funnen):

  | Fråga | A (blind ordning) | H (retrieval-ordning) | C* (orakel) |
  |---|---|---|---|
  | auto-renewal | 568 | **38** | 20 |
  | notice-period | 320 | **26** | 13 |
  | liability-cap | 525 | **47** | 34 |
  | confidentiality | 179 | **18** | 13 |
  | carveout | 244 | **16** | 7 |

- **Inbäddningsanalysen** (text-embedding-3-large, fråga↔chunk-cosinus) visade
  att gapet är ett *ordnings*problem: likhetsordning är 9–15× bättre än blind
  ordning, och JEV:s egna poäng är nästan oraklet. Därför byggdes arm H — en
  handkodad tvåfas-scanner (retrieval-index → JEV på kandidater) som stänger
  det mesta av gapet utan ett enda tränat steg.
- **Det kvarvarande H→C*-gapet är rankning, inte beslutspolicy:** de inlärda
  stop/budget-policyn (E och G) matchar arm H exakt på alla fem frågorna.
- **Kapitalkostnad:** retrieval-indexet kostar 78 Sweycoins engångs (uppmätt,
  1429 texter) under kalibreringsankaret, och arm H sparar 161–530 per fråga —
  break-even under en fråga.

## 3. Lärdomar från inlärningen (tre fällor, alla fångade av testerna)

1. **Frusen utforsknings-rng.** Klonade strategier ärvde master-policyns
   rng-tillstånd → varje träningsfråga utforskade identiskt → policyn frös på
   "eskalera alltid". Fix: per-fråga rng-tick. Detta är strategidokumentets
   "träningsbias"-risk, reproducerad och fixad i kod.
2. **Linjär överanpassning.** SGD på kollinjära, brusiga features extrapolerade
   vilt (continue lärde sig −6 mot empiriskt +1.5). Fix: medelvärdes-tabell över
   diskretiserat tillstånd — den kan inte extrapolera.
3. **Myopisk belöningsformning.** Lokal +9/−1-formning optimerade fel mål
   (84–210/500). Fix: episodisk kredit — och först då konvergerade policyn till
   C:s beteende.

## 4. Styrningslärdomar

- **Barn-AGENTS.md-mönstret fungerade:** experimentet körde under sina egna
  regler (frihet att utforska) med sex icke-förhandlingsbara kvalitetskrav
  (ärliga mätningar, hårda tak, facit-isolering, reproducerbarhet, inga
  irreversibla sidoeffekter, importriktning). Rotens produktionspolicy rördes
  aldrig — och "no fallbacks" visade sig förenligt med spekulativ exekvering
  så länge budget-tömning är ett högljutt terminaltillstånd, inte en tyst reservväg.
- **Mät signalen innan du bygger RL.** Inbäddningsanalysen kostade ören och
  räddade oss från att bygga ett inlärningsmaskineri kring fel fråga.

## 5. Medvetet inte byggt

Fas 2 (levande svar), fas 4 (portföljmarknaden), fas 5 (Epstein-skalning), de
195 övriga Golden Questions (dokumentnivåfrågor — annan harnessform), och
lär-till-rank för det kvarvarande H→C*-gapet.

## 6. Öppna frågor

- Rankning: kan en inlärd rankare (fusion av likhet + JEV-poäng) krympa det sista
  H→C*-gapet, och är marginalvärdet värt det?
- Skala: håller JEV:s 100 % goldträffar över hela 100-dokumentkorpusen?
- Fas 2: se [docs/architecture/living-answers-design.md](architecture/living-answers-design.md).
