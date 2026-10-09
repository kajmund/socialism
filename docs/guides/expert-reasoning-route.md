# Automatisk resonemangsprofil i expertchatten

Expertchatten bedömer varje texttur med Jev och väljer en befintlig logisk
LLM-profil:

- `fast` (Snabb) för direkta operationer och tydlig dokumentnavigation
- `balanced` (Balanserad) för normal expertinteraktion och osäkra bedömningar
- `deep` (Djup) för komplex analys, jämförelse, syntes eller motstridiga källor

Djup väljs också när uppgiften är kognitivt enkel men kräver agentiskt arbete över flera steg: tool orchestration, mängdoperationer, beroenden mellan steg eller completion tracking. Den bedömningen, reasoning-episoden och hur Jev inte ska ligga mellan varje tool call beskrivs i [expert-chat-reasoning-episode.md](../specs/expert-chat-reasoning-episode.md).

Jev returnerar endast separata scores för uppgiftsegenskaper. Reglerna i
`app/services/expert_reasoning.py` väljer profil deterministiskt. Provider,
modell och reasoning-inställningar kommer fortsatt från `llm_configurations`.
Varje profil som ska kunna väljas måste ha motsvarande `selection_role` och
`enabled_for_auto=true`.

`decomposable` och `parallelizable` ingår i samma bedömning men påverkar inte
profilen. På Djup, när båda ligger över `EXPERT_REASONING_SPAWN_*`, exponeras
`spawn_workers`. Se [expert-chat-worker-delegation.md](../specs/expert-chat-worker-delegation.md).

## Konfiguration

`EXPERT_REASONING_ROUTE_ENABLED=true` är standard. Sätt den till `false` för att
återgå till expertchattens tidigare modellval utan Jev-anrop.

Timeout, state-budget samt Snabb- och Djup-trösklar konfigureras med
`EXPERT_REASONING_*`-variablerna i `backend/.env.example`. Frågeschemat finns i
promptfältet `chat.expert.reasoning_assessment`.

Vid timeout, providerfel eller ogiltigt Jev-svar används Balanserad. Ett
verktygsresultat som materiellt ändrar uppgiften bedöms igen. Profilen kan höjas
från Snabb till Balanserad eller Djup och från Balanserad till Djup, men sänks
inte under samma tur.

## Kalibrering

Eventet `expert_chat.reasoning_routed` skrivs i datasetet
`socialism.expert_chat`. Det innehåller Jev-scores, initial och slutlig profil,
routing- och turn-latens, tool count, fallback samt eskaleringsorsak. Själva
användarmeddelandet loggas inte.

Kalibrera trösklar först efter att verkliga expertchattar visar profilfördelning,
latens och vilka initiala val som ofta behöver eskaleras.
