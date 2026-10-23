# Inventera befintliga faktapar- och konfliktmekanismer

Type: research
Status: resolved
Blocked by: –

## Question

Vilka befintliga komponenter och tidigare mätningar kan A2 och A3 återanvända,
och vad måste vara nytt? Detta är specens obligatoriska inventering (§3) och ska
ge ett faktounderlag till reuse-vs-new-besluten i A2/A3-ticketsen.

Inventera minst:

- **Tidigare Jev-experiment med passagefönster och explicita faktapar**:
  `backend/tests/research_reuse/jev_windows.py`,
  `jev_window_live.py`, `jev_window_controls.py`, `jev_passages.py`.
  Särskilt `contradiction_requests` (båda påståendena i state som
  `other_supplied_facts`), de märkta kontrollparen (`matching-dates`,
  `historical-change`, `different-contracts`) och vad som redan är mätt live.
  Sammanställ siffrorna med källa.
- **Persistenta fakta och TextUnits**: `graph_facts`, `graph_fact_relations`,
  `GraphFactView`, `TextUnit`-kopplingar, claims (`app/services/overgraph/`,
  `app/services/knowledge/`). Vad finns, vad är persistent vs endast i minnet,
  och vad kan läsas utan en produktions-DB?
- **Kandidatgenerering och embeddings**: befintliga sökvägar (Embedding,
  lexical index, OverGraph-relationer, entity/attribute-frågor) och deras
  kostnad/konfiguration.
- **Oberoende, dubbletter och kvalitet**: `quality.independence_key`, befintliga
  duplikat-/redundansbedömningar och `likely_duplicate_or_redundant`.
- **Routingsemantik**: `classify_research_decision`, `ASSESSMENT_QUESTIONS`,
  `ResearchJevDecision`-värden och var de konsumeras.
- **Trunkering/budget**: `assessment_input` (`ASSESSMENT_MAX_INPUT_CHARS`,
  `encode_assessment_input`), `jev_state_char_budget` och tidigare
  explicit-omission-mönster.
- **Golden cases och mätartefakter** i
  `backend/app/services/research/sufficiency_experiment/` och
  `backend/tests/integration/baselines/`.

Leverans: `.scratch/evidence-sufficiency-v2/research/01-inventering.md` med
fil-/radreferenser och en **reuse-vs-new-matris** per mekanism som A2/A3
behöver (dubblett vs oberoende, konfliktpost, claim-identitet,
kandidatgenerering, faktaparsbedömning, täckning). Markera vad som är mätt
tidigare, med vilken modell och vilka siffror, samt vilka luckor som återstår.
Föreslå inga nya abstraktioner; ticketen levererar fakta, inte design.

## Answer

Inventeringen finns i [01-inventering.md](../research/01-inventering.md) med fil-/radreferenser.

- Explicit faktapar finns bara i labbkoden `jev_windows.contradiction_requests` (båda påståendena, båda riktningarna) och är live-mätt: **16/16** riktade kontroller med `openjev-0.1`; ett negativt svar låg på **0,477 mot 0,5**. Automatisk parupptäckt finns inte.
- Produktionens och sufficiency-experimentets motsägelsefråga ställs på en enskild passage utan jämförelsepost; live-scores låg på **0,19–0,26** mot tröskel 0,6.
- `resolve_conflict` låter duplicate-score ≥ 0,6 lösa en konflikt, medan `independence_key` är oberoende av den. I trace avgjorde **0,57 vs 0,61** utfallet.
- `GraphFact*`-tabellerna är droppade av migration 192; OverGraph är auktoritativt och kan öppnas lokalt, men experimentet rör det inte. `write_fact(contradiction_key=...)` och `JevFactJudge` har inga produktionsanropare.
- `jev_state_char_budget` är **inte** research-Jev:s budget; den är `research_jev_max_state_chars=6000`.
- Matrisen täcker sex mekanismer. Kvar att besluta: kantlabel (`CONTRADICTS` vs `LINKED`), duplicate vs oberoende, persistent konfliktpost, claim- vs fact-identitet, kandidatgenerering, täckningsnivåer 3–5 samt golden cases utan negativa par.
