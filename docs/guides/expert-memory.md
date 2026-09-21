# Expertminne med Mem0

Mem0 OSS använder samma Supabase Postgres-databas som backend. Vektorer lagras
med pgvector och Mem0-historiken ligger i vanliga Postgres-tabeller. Ingen lokal
Chroma- eller SQLite-databas används i drift.

## Lagring och scope

- Vektorer: `expert_memories` och `expert_memories_entities`
- Mem0-historik: `mem0_history` och `mem0_messages`
- Kundscope: `user_id=kund:{customer_id}`
- Expertscope: `agent_id=expert:{catalog_key}`. Samma stabila katalognyckel används
  i expertchat och panel så att båda ytorna delar expertens minne.

Minnen delas aldrig mellan kunder. `persona_messages` och
`panel_sessions.transcript` är fortsatt den ordagranna konversationshistoriken.
Mem0 innehåller extraherade långtidsminnen.

## Skriv- och läsvägar

- Expertchat skriver text- och bildturner och söker relevanta minnen före svar.
- Expertkonsultation skriver `expert_consult` för både den frågande och den
  svarande experten. Båda minnena innehåller den omformulerade frågan, vem som
  frågade respektive svarade och kollegans svar.
- Intent-svar skrivs per expert och identiska payloads hoppas över.
- Word-granskning skriver destillerade findings efter lyckad körning.
  Findings ersätts per `kund × expert × doc_id`; oförändrat innehåll hoppas över.
- Word-granskningens egna LLM-anrop läser inte minnet i fas 1.
- När en generell researchfråga får fryst evidens sparas ett kort
  `research_receipt` hos varje expert som ställde eller ansvarade för frågan.
  Kvittot pekar på `knowledge_question_id` och `source_attempt_id`; själva
  evidensen ligger fortsatt i det generella kunskapslagret och kopieras inte
  till Mem0.

Expertchatten kan därför minnas att experten redan har fått ett svar utan att
blanda ihop expertens personliga långtidsminne med den gemensamma evidensen.
Chatten gör samtidigt en semantisk, kundavgränsad sökning efter den kanoniska
frågan och använder bara evidens från ett fryst EvidenceSet. Ett minneskvitto
är aldrig i sig en källa eller ett tillräcklighetsbeslut.

Minnesfel får avbryta anropet. Det finns ingen alternativ provider eller tyst
degradering.

Admin kan lista minnen via `GET /expert-memory` och ändra dem med
`PATCH/DELETE /expert-memory/{id}`. `DELETE /expert-memory` rensar enligt
samma `customer_id` / `expert_id`-filter som listningen. Expertchatten läser
`GET /personas/{id}/memories`, uppdaterar med `PATCH/DELETE
/personas/{id}/memories/{memory_id}`, rensar experten med
`DELETE /personas/{id}/memories`, och får `saved_memories` i chattsvaret
när en tur extraherar nya eller uppdaterade fakta.

Mem0:s extraktion får `custom_instructions` / `prompt` som kräver att minnen
skrivs på källmeddelandets språk — ingen översättning till engelska.

## Bilder

Mem0 körs med `enable_vision=True`. Bilden läses från den befintliga
SHA256-cachen och skickas som base64 data-URI till den konfigurerade
Cerebras-modellen (`MEM0_VISION_MODEL`, standard `qwen-3.8-27b`). GPT- och
`gpt-oss`-modeller tillåts inte för Mem0 vision.

Vid **skrivning** extraherar vision-klienten fakta från bild + text. Vid
**sökning** beskriver samma pipeline bilden till text (Mem0 `search()` tar
bara en sträng) och den texten används mot pgvector. En bild utan
bildtext är ett giltigt sökunderlag.

pgvector-tabellerna lagrar de textfakta som Mem0 extraherar. `image_sha256` sparas som
metadata och exponeras i API/UI så att man kan se bilden i minnesloggen;
råa bildbytes lagras inte i Mem0. Om extraktionen inte hittar ett
nytt faktum sparas visionbeskrivningen tillsammans med bilden (`infer=False`)
så att bildturen ändå hamnar i minnet.

## Lokal verifiering

Standardtesterna använder en fake vid Mem0-gränsen och gör inga nätverksanrop:

```bash
cd backend
uv run pytest tests/test_expert_memory.py
```
