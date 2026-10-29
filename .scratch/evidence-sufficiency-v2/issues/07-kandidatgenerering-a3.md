# Kandidatgenerering för faktapar (A3)

Type: grilling
Status: resolved
Blocked by: 01, 06

## Question

Hur väljs de faktapar ut som ska jämföras — konservativt nog att inte missa
motstridiga värden, men utan fullständig parvis jämförelse?

Beslut som ticketen ska låsa:

- Indata: claim-kandidater från `claims.py` (ticket 06). Använd bara
  `extraction_status="extracted"`; behåll `claim_id`/`evidence_id`/`source_id`
  så att källförekomster aldrig slås ihop. `canonical_key`, `entity_id` och
  giltighetstid är urvalsattribut, inte identiteter.
- Återanvändning: det befintliga explicita paret i
  `tests/research_reuse/jev_windows.py` (`contradiction_requests`,
  `other_supplied_facts`) och de märkta kontrollparen — vad kan återanvändas
  direkt, vad behöver generaliseras?
- Kandidatkällor: gemensam entitet/attribut, matchande `ResearchNeed`/sakområde,
  OverGraph-relationer, embedding-likhet. Vilka används i experimentet, med
  vilken provider/kostnad, och vilka är deterministiska filter?
- Konservativitet: motstridiga värden kan ha olika embeddings (3 vs 6 månader,
  2026 vs 2027, automatisk förlängning vs skriftlig överenskommelse). Vilken
  regel fångar dem, och hur undviks att hög recall blir parvis explosion?
- Spårbarhet: spara valda par med urvalsorsak, och möjliga par som inte kunde
  bedömas på grund av budget eller saknad kontext. Hur räknas detta som
  "conflict candidate coverage"?
- Testfall som måste ingå: de fyra exemplen i specen §7.2.
- Offline-nivå: experimentet är i dag helt DB-fritt, men OverGraph kan öppnas
  mot en lokal katalog. Ska A3 köra på enbart `AssessableEvidence`, eller får
  det läsa lokal OverGraph? Embeddings kräver `OPENAI_API_KEY` och nätverk —
  vilken väg är obligatorisk i huvudmätningen?

Leverans: kandidatalgoritm (steg, filter, budget) + datastruktur + spårbarhet,
redo att kopplas till faktaparsbedömningen.

## Answer

**Beslut 2026-10-22 (grilling med användaren), med tre preciseringar.**
Implementerat i commit `b2125e7e` på `feat/sufficiency-a3-claims`. Inga
Jev-anrop: detta mäter om rätt par föreslås, inte om Jev bedömer dem rätt.

### Låst beslut

| Fråga | Beslut |
| --- | --- |
| Q1 Par-facit | Godkänt, två lager (`candidate_pairs` + `contradiction_pairs`) |
| Q2 Strategier | A deterministisk, B embeddings, C hybrid — mäts separat |
| Q3 Budget/mått | `max_pairs_per_need=40`, recall prioriteras; rank, källor och omissions sparas |
| Q4 Deterministisk signatur | Godkänd, men **ingen automatisk exkludering via canonical_key** |
| Q5 Embeddings | Godkänd, recall före **och** efter budget; källor A/B/båda sparas |
| Q6 Tail-fall | Enkelt tail-fall nu; svårare semantiskt tail-fall i nästa benchmarkversion |

### Preciseringar

1. `canonical_key` är gruppering, inte bevis på förenlighet. Identiska nycklar
   downviktas (×0.5) men exkluderas aldrig; endast en uttryckligt verifierad
   ekvivalensregel får utesluta ett par (ingen sådan finns ännu).
2. Hybridens union kan bli större än 40 par. Därför mäts `recall_before_budget`
   och `recall_at_budget` separat, plus källor (`deterministic`/`embeddings`/båda)
   och slutlig rank per facitpar.
3. Enkelt tail-fall nu; svårare semantiskt tail-fall (motsägelse utan tydligt
   tokenöverlapp) ligger i kartans "Not yet specified" som nästa
   benchmarkversion.

### Implementation

`pairs.py`: `select_pairs(claims, needs, strategy, config, embedding_provider)`
→ `PairSelection(candidates, selected, budget, omitted_by_budget, input_claims,
latency_ms, embedding_calls, embedding_texts)`.
`PairCandidate(pair_id, need_id, left/right_claim_id, score, sources, features)`.
Config: `max_pairs_per_need=40`, `embedding_neighbors=3`.

- A: delade `entity_id`/`definition_id`, sällsynthetsviktad innehållstoken,
  frågetoken; temporal metadata är feature, inte filter.
- B: `text-embedding-3-large`, top-3 cosine-grannar per claim.
- C: union med kombinerad score; par från båda behåller båda källorna.
- Facit: `pair-gold-v1.json`; `unknown_counterpart` är negativ kontroll med tomt
  facit och exkluderas från recall-aggregatet.
- Nytt fall: `tail_claim_contradiction` (180 kandidater, motsägelsen sist).

### Mätresultat (`pair-recall-v1.json`, `text-embedding-3-large`)

| Fall | A rank/vald | B rank/vald | C rank/vald |
| --- | --- | --- | --- |
| `duplicate_contradiction` | 1 / ja | 2 / ja | 1 / ja |
| `independent_contradiction` | 1 / ja | 1 / ja | 1 / ja |
| `compatible_periods` | 1 / ja | 1 / ja | 1 / ja |
| `compatible_entities` | 1 / ja | 1 / ja | 1 / ja |
| `tail_claim_contradiction` | 1 / ja | **340 / nej** | 1 / ja |

Sammanfattning (fem positiva fall): A recall 1.00/1.00, B 1.00/0.80, C
1.00/1.00 före/efter budget. A väljer 44 par med 0 embeddinganrop; B och C
väljer 48 par med 5 embeddinganrop. Tail-fallet är poängen: embeddings hittar
paret före budget men rankar det 340, så det sorteras bort; hybrid behåller det
på rank 1. Valda par är den framtida Jev-anropsbudgeten.

### Verifiering

`tests/test_sufficiency_experiment_pairs.py` (8 tester): deterministisk recall
före/efter budget, canonical_key exkluderar inte, budget kan släppa ett par som
hittades före budget, embeddings kräver provider, fake-provider för B/C inkl.
källor, facit-id:n löser ut, negativ kontroll separat, omvänd parordning ger
samma id. 73 sufficiency-tester gröna, ruff och maintainability gröna.
