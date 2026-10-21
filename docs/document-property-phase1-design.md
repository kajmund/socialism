# Fas 1-design: dokumentegenskaper som typade claims i OverGraph `knowledge`

Underlag från exakt inventering av `backend/app/services/knowledge/`,
`backend/app/database/models.py`, `backend/app/services/overgraph/`. Detta
dokument beskriver **hur** dokumentegenskaper mappar mot verklig kod, och
vilka beslut som måste låsas innan kod skrivs.

## 1. Vad koden faktiskt redan har (exakt)

### Claims (domänneutrala påståenden)

`KnowledgeClaimRecord` (`knowledge_claims`):

| Kolumn | Typ | Betydelse |
|---|---|---|
| `id` / `identity_key` | String(64) | `sha256(scope_key \0 predicate \0 canonical_json(normalize_assertion(value)))` |
| `predicate` | String(128) | Adapter-väljer betydelse |
| `value` | JSON | Det normaliserade påståendet |
| `scope_type` / `scope_key` / `customer_id` | | Tenant-scope |
| `superseded_at` / `successor_id` | | Temporal livscykel (supersede, ej overskriv) |

**Ingen `status`-kolumn.** Identity-normaliseringen (`identity.py`) tar bort
volatila nycklar (`citation`, `excerpt`, `explanation`, `rationale`, …) ur
`value` men behåller övriga nycklar. Det betyder två saker:

1. **Dokumentidentitet måste ingå i `value`** (t.ex. `document_id`), annars blir
   `predicate + value` samma claim för alla dokument.
2. **Verifieringsstatus får inte ingå i `value`**, annars ändras claim-identiteten
   när status ändras (SUPPORTED → UNDECIDED).

### Evidens (SUPPORTED_BY)

`KnowledgeClaimTextUnit` (`knowledge_claim_text_units`): `claim_id`,
`text_unit_id`, `ordinal`, `relation` (= `SUPPORTED_BY`). Detta är claim →
TextUnit-länken. `supporting_text_unit_ids_for_quote` (claims.py) mappar ett
citat till TextUnits utan LLM.

### Relationer (claim ↔ dokument)

`KnowledgeRelationshipRecord` (`knowledge_relationships`): `relation`,
`from_kind`/`from_id`, `to_kind`/`to_id` (`entity|claim|text_unit|document`).
`CORE_RELATIONS = {ABOUT, SUPPORTED_BY, CONTRADICTS, PART_OF, SAME_AS}`.
Dokumentnod = `CanonicalDocumentRecord`. En claim kan knytas till dokument med
`relation = "ABOUT"` eller en namnsatt adapterrelation (`.` i namnet).

### Övriga "status"-begrepp (ingen är verifieringsstatus)

- OverGraph FACT `props.status = "active"` (write.py) — graffaktens livscykel.
- `KnowledgeAnswerReview.status` (`awaiting_ttl | scheduled | candidate | completed`) — TTL.
- `superseded_at`/`successor_id` — temporal ersättning.

**Slutsats: det finns ingen befintlig SUPPORTED/UNSUPPORTED/UNDECIDED-status på
claims.** Den måste antingen läggas till eller modelleras som en separat
observation — i linje med specens §11 ("UNSUPPORTED … är en
sök-/verifieringsobservation, inte ett negativt claim").

## 2. Föreslagen modell

```
deterministisk discovery  →  kandidat (document-property + citerad TextUnit)
        │
        ▼
Jev-verifiering (SUPPORTED / UNSUPPORTED / UNDECIDED, source-grounded)
        │
        ├─ SUPPORTED  →  KnowledgeClaim  (domain_knowledge, SUPPORTED_BY TextUnits)
        │
        └─ UNSUPPORTED / UNDECIDED  →  verifieringsobservation (inte ett claim)
```

- **Durable claim** = bara verifierade egenskaper. `predicate = class_id`,
  `value = {document_id, value, polarity, taxonomy_version}`. SUPPORTED_BY-länk.
- **Kandidat/observation** = UNSUPPORTED/UNDECIDED, så att lookup kan visa
  "stödda" respektive "ej verifierade" separat (spec §12.2).
- **Negativ egenskap** = egen claim med `polarity = "negative"` + SUPPORTED_BY
  den negativa klausulen; `CONTRADICTS` knyter ihop positiv/negativ om båda finns.

## 3. Beslut att låsa (med rekommendation)

**D1 — Var ligger verifieringsstatusen?**
Rekommendation: ingen ändring av `knowledge_claims`; SUPPORTED blir claim,
UNSUPPORTED/UNDECIDED blir rader i `knowledge_observations`
(`observation_class="document_property_verification"`, `kind="verification"`,
`document_version_id` + claim-identity + status + källa). Det återanvänder
befintlig observationmodell och lämnar claim-identiteten ren.

**D2 — Kandidatlagret.** Discovery-kandidater före verifiering: behöver vi
spåra dem separat (för asynkron kö, §13), eller räcker att generera dem per
körning och bara spara verifieringsresultatet? Rekommendation: spara kandidaten
som observation vid verifiering (ej före), och håll kön på befintliga jobb/lease
(`research_worker.py`-mönstret).

**D3 — Property lookup-index.** `knowledge_claims.predicate` saknar index.
Rekommendation: Alembic-migrering med index på
`(scope_key, predicate, superseded_at)` och ev. ett JSON-uttryck för
`value->>'value'`. Lookup = SQL-uppslag, inte semantisk sökning.

## 4. Fas 1 (vertikal skiva) — konkret

1. Ny modul `app/services/document_properties/` (discovery + verifiering + lookup),
   följer DB→extern→DB-regeln.
2. Discovery: deterministisk extraktion mot `TextUnitRecord` + struktur; ingen LLM.
3. Jev-verifiering: prompt-text från `prompt_fields` (ej hårdkodad), källförankring
   via `supporting_text_unit_ids`/`validate_source`-mönstret.
4. SUPPORTED → `persist_knowledge_claim`; UNSUPPORTED/UNDECIDED → observation.
5. Property lookup: SQL över `knowledge_claims` (predicate + scope + paginering).
6. Tester: enhetsnivå, DB-anslutning släpps före externa anrop (1-anslutningspool).

## 5. Kända återstående punkter (inte blockerande för fas 1)

- Prompt-seedning för Jev-kontraktet (vilken prompt-nyckel/modul).
- Exakt `knowledge_observations`-schema (läsas innan D1 implementeras).
- Lokal dense: `TextUnitRecord.embedding_id` → vektor; frågetext från
  användarfråga (spec §10), ej gold.
