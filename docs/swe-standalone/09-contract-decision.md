# 09 — Kontraktsbeslut för B1–B3

**Status:** Beslutsunderlag enligt projektägarens direktiv. Detta dokument ska
godkännas **före** PR 1 (B1). Det ändrar ingen produktionskod.
**Gäller:** PR 1 (`10`), PR 2 (`11`) och PR 3 (`12`). Ordningen enligt
`07-go-no-go.md` §0: **kontraktsdesign först, implementation sedan.**
**Principer från specen:** deterministiska kontrakt har företräde; inga
parallella implementationslager; ingen onödig bakåtkompatibilitet.

## 1. Syfte

Projektägarens huvudsakliga invändning mot den första planen var att B1
(beroendeinversionen i Python) annars riskerar att abstraheras mot ett
gränssnitt som ändras när B2 flyttar behovs- och operationsmodellen till Rust.
Det här dokumentet låser därför de fem besluten innan någon implementation
påbörjas:

| # | Beslut | Konsekvens för PR |
| --- | --- | --- |
| D1 | **Rust är enda sanningskällan för behovs-, evidens- och operationssemantik**; Python är adapter | B1 inverterar mot serialiseringskontrakt, inte mot Python-typer; B2 implementerar semantiken i Rust; B3 gör journalen till motorgaranti |
| D2 | **Versionssatta serialiseringskontrakt** mellan Rust och Python | Varje korsad gräns bär `schema_version`; avvisning sker typat, inte tyst |
| D3 | **Journalen skiljer försök, bekräftelse och debitering**; exakt-engångs*exekvering* av externa verktyg är inte en motorgaranti | B3 inför `InvocationAttempt` / `ConfirmedResult` / `ChargeRecord`; demon får fler tester |
| D4 | **SWE äger mekanismen, inte domänens innehåll** | B2:s acceptanskriterier får ett explicit ramverksstopp (`§5`) |
| D5 | **B1 motverkar inte framtida flytt:** Python-adaptern exponerar exakt de exporter som redan finns | B1 är en rigorös omdirigering, inte en ny API-yta; Research-imports ändras inte |

## 2. Sanningskälla: Rust normativ, Python adapter

### 2.1 Ägandematris

| Semantik | Ägare | Python-adapterns roll |
| --- | --- | --- |
| Uttryck, routing, fork/join/map, limits, idempotens för completions | **Rust** (idag `swe-native`) | Skickar JSON-frågor, får JSON-svar; aldrig egen logik |
| Behov: derivationsregler, `NeedMore`-skydd, prioritets- och statusövergångar | **Rust** (B2) | Projekterar domänens behov till generiska typer; läser resultat |
| Evidens: tillståndsövergångar, konfliktregel, fullständighetskrav | **Rust** (B2) | Levererar kandidater; härleder aldrig `VERIFIED` själv |
| Operationer: `OperationSpec`, grind, `OpOutcome`, `INSUFFICIENT_EVIDENCE` | **Rust** (B2) | Registrerar exekutorer; grind och utfall bestäms i Rust |
| Budget och kostnadsredovisning | **Rust** (`swe-budget`) | Levererar tariff och faktisk kostnad per anrop |
| Faktatyper, normalisering, verifieringsregler, undersökningsstrategi | **Socialism** | Äger domänens tolkning helt |

### 2.2 Regler som följer

1. **Ingen semantikduplicering.** En övergång (t.ex. "ett behov är RESOLVED")
   får finnas i exakt en implementation. Python får läsa resultatet och
   presentera det, inte beräkna det.
2. **Python får inte "fixa" ett Rust-svar.** Om Rust säger
   `INSUFFICIENT_EVIDENCE` är det utfallet; adaptern får inte räkna om,
   komplettera eller gissa.
3. **Fronter:** `compile`/`validate` kan fortsätta i Python under övergången,
   men när B2 är klar är Rust normativ även där (`04` §1.7 G1) — Python
   validering blir ett tidigt, snabbare filter, inte en sanningskälla.
4. **Mätbar kontroll:** ett differentialtest (samma indata → samma utfall) är
   obligatoriskt i B2 för varje semantik som flyttas. Avvikelse är en bugg,
   inte en fallback.

### 2.3 Konkret exempel på vad som inte får hända

Det scenario projektägaren nämnde:

```
Python: need C1 -> RESOLVED        (extra+JEV-adapter säger att evidensen räcker)
Rust:   need C1 -> UNRESOLVED      (grind: evidensen är AMBIGUOUS)
```

Detta får inte vara möjligt efter B2, eftersom:

- Python aldrig äger `RESOLVED`-övergången — adaptern skickar
  evidenskandidater, Rust härleder behovsstatusen (§3, schema
  `swe.evidence_candidate.v1` → `swe.need_state.v1`);
- operationens grind läser Rust-statusen, inte domänstatusen;
- differentialtestet i B2 pinnar att Python-adapterns projektion ger samma
  tillstånd som den rena Rust-vägen.

## 3. Versionssatta serialiseringskontrakt

Allt som korsar Rust↔Python-gränsen är ett **typvärde med
`schema_version`**. Versionen avser datatypen, inte motorversionen.

| Kontrakt | Riktning | Version | Innehåll | Ägare |
| --- | --- | --- | --- | --- |
| `swe.workflow_definition` | Python → Rust | `1` (SWD `1.0`) | Dokument + kanonisk hash | Rust |
| `swe.effect` | Rust → Python | `1` | `invoke_handler` / `invoke_provider` / `cancel_invocation` | Rust |
| `swe.completion` | Python → Rust | `1` | `invocation_id`, `outcome` (`ok`/`error`/`cancelled`), `payload`, `error{kind,message,path}` | Rust |
| `swe.need_spec` | Python → Rust | `1` (B2) | `id`, `kind`, `priority`, `cardinality`, `scope?` | Rust |
| `swe.evidence_candidate` | Python → Rust | `1` (B2) | `need_id`, `value?`, `provenance{source_id, locator?, content_hash?, retrieved_at?, provider?}`, `confidence_bp?`, `conflict_group?` | Rust |
| `swe.need_state` | Rust → Python | `1` (B2) | `need_id`, `status` (`UNRESOLVED`/`RESOLVED`/`AMBIGUOUS`), `reason`, `evidence_ids` | Rust |
| `swe.operation_outcome` | Rust → Python | `1` (B2) | `status` (`answer`/`need_more`/`insufficient_evidence`), `value?`, `needs?`, `missing[]` | Rust |
| `swe.journal` | Rust ↔ förvar | `1` (B3) | Run-snapshot, attempts, confirmed results, charges, events | Rust |
| `swe.event` | Rust → konsument | `1` | `EventKind` + `seq` + lineage (`events.rs`) | Rust |

Regler:

1. **Okänd version = typat fel** (`unsupported`, `04` §1.5-anda). Ingen
   tyst konvertering, ingen fallback till "senaste".
2. **Replay måste använda samma version som journalen:** resume avvisar en
   journal vars version motorn inte kan läsa exakt.
3. **Kanonisk JSON** (`canonicalize`) för allt som hashas eller lagras;
   `schema_version` ingår i det hashas underlaget där det är relevant.
4. **Versionsbump kräver:** ny enum-variant eller ändrat fältnamn; tillägg av
   valfritt fält *utan* semantisk påverkan kräver ingen bump men ska
   dokumenteras.
5. **Inga bakåtkompatibla shims** medan det inte finns kunder; bara exakta
   versioner (`06` §5).

## 4. Journalen: försök, bekräftelse och debitering

### 4.1 Problemformulering

Referensexperimentet visar **exakt-engångsdebitering** vid resume: ledger-event
replayas och ingen dubbeldebiteras. Det är korrekt — men det är en ekonomisk
garanti, inte en garanti om externa sidoeffekter. Vid en krasch efter att ett
externt verktyg utförts men före journalföringen kan ett försök ha runnit iväg
utan att resultatet finns. Motorn får inte påstå annat.

### 4.2 Tre tillstånd

```text
InvocationAttempt  { attempt_id, invocation_id, action, started_at_ms,
                     idempotency_key }
ConfirmedResult    { invocation_id, attempt_id, outcome, payload, confirmed_at_ms }
ChargeRecord       { charge_id, invocation_id, attempt_id, amount_milli,
                     tariff_milli, idempotency_key, state: reserved|settled|released }
```

Regler:

1. **Ett försök bokförs innan åtgärden utförs.** Journalen medger därför
   "försök utan bekräftelse" — ett ärligt tillstånd, inte ett fel.
2. **Bekräftat resultat är det enda som räknas som exekverat.** Ett försök utan
   bekräftelse vid resume blir *inte* automatiskt "gjort"; motorn frågar
   åtgärden via idempotensnyckeln (se 4.3) eller rapporterar
   `unconfirmed_attempt` typat.
3. **Debitering följer reservationen, inte försöket.** En avbruten, obekräftad
   åtgärd ska släppa reservationen (`release`), inte debiteras; en bekräftad
   åtgärd debiteras exakt en gång (`settle` med samma nyckel).
4. **Idempotensnyckeln är deterministisk och delas med den externa åtgärden:**
   `idempotency_key = sha256(run_id, invocation_id, action, attempt_index)`.
   En provider som stödjer idempotens (eller en host som gör det lokalt) kan då
   avgöra om åtgärden redan utförts.
5. **Journalen är append-only och replaybar:** `Ledger::replay` för ekonomi,
   kompletions-replay för maskinen, attempts för ärlighetsbedömningen.

### 4.3 Återhämtningsstrategier (väljs av hosten, deklareras i journalen)

| Strategi | När | Vad motorn gör | Vad hosten måste göra |
| --- | --- | --- | --- |
| `replay_result` | Åtgärden är ren/deterministisk (mock, fryst fixture) | Replayar bekräftat resultat, ingen ny exekvering | Inget |
| `idempotent_retry` | Åtgärden stödjer idempotensnyckel | Nytt försök med **samma** nyckel; debiterar bara om åtgärden bekräftat ett nytt svar | Levererar idempotens i sin klient |
| `unconfirmed_abort` | Åtgärden har oåterkalleliga sidoeffekter och ingen idempotens | Stoppar typat (`unconfirmed_attempt`), ingen gissning, ingen dubbeldebitering | Löser manuellt eller markerar run som overifierad |

Ingen av strategierna är en tyst fallback: valet står i journalen
(`recovery: replay_result | idempotent_retry | unconfirmed_abort`) och
granskas i PR 3.

### 4.4 Vad referensexperimentet bevisar idag

| Påstående | Status |
| --- | --- |
| Exakt-engångs**debitering** vid resume | **Bevisat** (ledger-eventloggen är identisk; 46 000 milli i båda fallen) |
| Exakt-engångs**exekvering** av lösta/mockade åtgärder | **Bevisat för deterministiska åtgärder** (33 unika invocations i båda fallen) |
| Exakt-engångs**exekvering av externa verktyg** | **Inte bevisat och inte påstått** — kräver idempotens eller kvittens från toolens sida (PR 3) |

## 5. Ramverksgränsen för B2 (SWE äger mekanismen, inte innehållet)

SWE ska äga:

| Mekanism | Exempel |
| --- | --- |
| Behovsmodellens form och övergångar | `UNRESOLVED`→`RESOLVED` endast från VERIFIED, icke-ambiguös evidens; prioritet/kardinalitet som data |
| Bevisat-nya-behov-protokollet | `NeedMore(NeedRef)`, skydd mot identisk upprepning, avslut i `INSUFFICIENT_EVIDENCE` |
| Grinden | `required_inputs`, `ALL_REQUIRED`, `on_missing` |
| Evidenstillståndens semantik | VERIFIED/AMBIGUOUS/REJECTED-regler*, konflikt = AMBIGUOUS, REJECTED räknas aldrig |
| Budgetens mekanik | reservation, settle, release, idempotens, kostnadsredovisning |

\*Tillståndsreglerna är generiska: "flera källor som inte kan förena sig" →
AMBIGUOUS, "ingen källa/ingen proveniens" → REJECTED. **Vilka källor som får
tala, och vad som räknas som konflikt, är domänens beslut** och injiceras som
konfliktpolitik/troskel — inte hårdkodas i `swe-core`.

SWE ska **inte** äga:

| Innehåll | Varför inte |
| --- | --- |
| Faktatyper (`notice_period`, `c_exception`, `price_sek`) | Domänbegrepp |
| Verifieringsregler (hur en JEV- eller GLiNER2-bedömning blir VERIFIED) | Domänens epistemologi |
| Normalisering (månader, datum, belopp) | Domänens semantik |
| Undersökningsstrategi (vilka källor, vilken ordning, vilken budget) | Domänens policy; SWE erbjuder `Policy`-kontraktet (`04` §7) |
| Exekutorer (`MAX_NOTICE_PERIOD`, `APPLY_EXCEPTION`, `select_cheapest`) | Domänens operationer |

**Acceptanstest i B2:** om en typ eller regel bara kan beskrivas med
domänord (avtal, JEV, chunk, uppsägningstid) får den inte hamna i `swe-core`
utan måste injiceras. `05-gym-split.md` §7:s grep-gate utökas till att gälla
även de nya `swe-core`-modulerna.

## 6. B1 utan att göra Python-adaptern självständig för tidigt

Invändningen är giltig: om B1 inför en ny Python-API-yta som senare flyttas till
Rust, gör vi arbete två gånger. Därför:

1. **B1 ändrar bara *var* saken bor, inte *vad* Python erbjuder.** Alla fem
   ändringar är rena omdirigeringar (se `10` §2), och `backend/app/swe`
   behåller exakt samma publika exporter.
2. **B1 inför inga nya behovs-/evidens-/operationstyper i Python.** De väntar på
   B2 och kommer att vara Rust-ägda från början.
3. **B1:s injektionspunkter är de som `04` §2–§6 redan definierar**
   (`prompt_keys`, `providers`, `prompts`+renderare, `cache`, `run_store`) — de
   överlever flytten till Rust eftersom de är host-kontrakt, inte
   engine-typer.
4. **Research rörs inte:** `swe_bridge.py` och research-handlers behåller sina
   imports (de importerar redan publika `app.swe`-namn).

## 7. Vad varje PR får och inte får göra

| PR | Får | Får inte |
| --- | --- | --- |
| 1 (B1) | Flytta JEV-provider, prompt-renderare, prompt-key-whitelist och feature/host-modell ut ur `app/swe`; lägga till import-gate och injektionstester | Ändra researchbeteende; införa nya semantiktyper; ändra SWD-format |
| 2 (B2) | Lägga till generic needs/evidence/operations i Rust; låta Python projektera; differentialtester | Låta Python behålla en egen övergång; lägga domänbegrepp i `swe-core`; ändra researchresultat |
| 3 (B3) | Journal-/resume-kontrakt, attempts/confirm/charge, recovery-strategier, Rust-journal i demon | Påstå exakt-engångs*exekvering* av externa verktyg; ändra övergripande run-semantik för Research |

**Gemensamt för alla tre:** Research- och research-wiring-testerna förblir gröna;
inga ändringar i `crates/swe-gym`; ingen fysisk repo-flytt.
