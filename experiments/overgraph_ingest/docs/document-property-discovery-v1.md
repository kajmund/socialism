# Spec: Dokumentegenskaper som oberoende discoverysignal

**Projekt:** Socialism, `kajmund/socialism`
**Arbetsområde:** `experiments/overgraph_ingest/`
**Omfattning:** Ett isolerat experiment. Ingen ändring av produktionssökning, standardretrieval eller `--bm25-compare`.

## 1. Syfte och hypotes

Tidigare experiment visar att dense hittar rätt underlag lokalt i ~99 % av fallen (CE@5), medan dokumentidentifiering är den bindande förlusten — och att passageaggregering inte åtgärdar den.

**Primär hypotes:** Om vi extraherar och förankrar juridiska dokumentegenskaper redan vid ingest, kan Overgraph bli ett **sökbart register över vilka juridiska förhållanden varje avtal reglerar** — i stället för att experten varje gång semantiskt genomsöker tusentals TextUnits.

**Avgränsning:** Detta är ett **kapabilitetstest för nio förregistrerade egenskaper**, inte ett starkt generaliseringstest. Överförbarhet till helt nya juridiska relationer testas i ett senare, separat experiment med en egen held-out-konceptmängd.

**Arkitekturprincip:** En dokumentegenskap är ett **index över evidensen, inte en ersättning för evidensen**. Discovery använder egenskaperna för att hitta dokument; Verification läser tillbaka de pekade TextUnits och bedömer om stödet verkligen finns och har rätt polaritet.

## 2. Två spår

| Spår | Signal | Modell/embedding | Körkostnad |
|---|---|---|---|
| **A. Deterministic structure** | Befintliga rubriker, klausulnummer, strukturträd + förregistrerad begreppslexikon | Ingen | Ingen |
| **B. General property extraction** | Jev extraherar relationer från dokumentets struktur + text, förankrade i excerpts | Jev, en call per dokument vid ingest | En gång per dokument, redovisas separat |

A mäts först; B körs om A inte återfinner tillräckligt många av de tidigare missade dokumenten. B får den allmänna taxonomin, inte testfrågorna och inte facit.

## 3. Egenskapsmodell

| Fält | Innehåll |
|---|---|
| `class_id` | Typad relation, t.ex. `governing_law`, `confidentiality_obligation` |
| `value` | Värde eller boolean, t.ex. `"Sweden"`, `true` |
| `polarity` | `positive` / `negative` — en text kan uttrycka att egenskapen *inte* föreligger |
| `source_unit_keys` | Stabil nyckel till de TextUnits som stöder egenskapen |
| `excerpts` | Exakt delsträng ur varje källenhet |
| `origin` | `structure` (A) eller `jev` (B) |
| `extraction_version` | Version av taxonomi/extractor |
| `confidence` | Endast B; råvärde, aldrig ensamt en status |

### 3.1 Evidensförankring är inte verifiering

Att en excerpt återfinns i originaltexten bevisar bara att citatet existerar. Därför skiljer vi tre nivåer:

| Nivå | Definition | Vad den bevisar |
|---|---|---|
| `GROUNDED` | Excerpten är en exakt delsträng av en citerad TextUnit (`validate_source`) | Citatet finns |
| `SUPPORTED` | Excerpten påstår egenskapen med rätt polaritet och claim-form | Egenskapen har stöd |
| `UNDECIDED` | Stödet är oklart (rubrik, hänvisning, grammatiskt negativ/omodlad) | Inget ännu |

- Enbart `GROUNDED` får aldrig bli `verified`. `verified` kräver `SUPPORTED`.
- Polaritet är avgörande: ”Detta avtal innehåller ingen sekretessförpliktelse” är `GROUNDED` för en *negation*, men `SUPPORTED` för `confidentiality_obligation = false` — inte för `true`.
- Detta återanvänder befintlig polaritets-/claim-form-diagnostik (`overgraph_ingest/coverage/proof.py`, `proof_gate`, `proof_logic`).

## 4. Allmän relationstaxonomi (förregistrerad, versionerad)

Taxonomin är en allmän kontraktsrelationstaxonomi som definieras och fryses före utvärderingen. De nio utvärderingskoncepten är en delmängd; extraheringsprompten ser bara taxonomins definitioner, aldrig frågetext och aldrig facit.

| `class_id` | Definition |
|---|---|
| `governing_law` | Tillämplig rätt/jurisdiktion |
| `confidentiality_obligation` | Operativ tystnads-/sekretessplikt |
| `termination_notice` | Uppsägningstid/uppsägning |
| `automatic_renewal` | Stående automatisk förlängning |
| `liability_limitation` | Ansvarsbegränsning/tak eller friskrivning av indirekt skada |
| `liability_secrecy_carveout` | Undantag från ansvarsbegränsning vid sekretessbrott (sammansatt) |
| `force_majeure` | Befrielsegrund vid oförutsedda händelser |
| `personal_data_processing` | Personuppgifts-/GDPR-reglering |
| `assignment_restriction` | Överlåtelse-/cessionsförbud |

Gold→egenskapsmappning deklareras separat och hashas. Ett senare **överförbarhetstest** använder en helt ny, otestad egenskapsmängd med egen held-out-split; det rapporteras inte här som generalisering.

## 5. Anti-läckage och split

1. Taxonomin är förregistrerad och versionerad; ingen termin läggs till efter att resultat lästs.
2. B-prompten får endast taxonomins definitioner och dokumentets struktur/text — inte testfrågorna, `contains` eller `classify_question`.
3. Gold→egenskapsmappning är en separat, förfryst tabell.
4. Utvecklingssplit: de fem sedda golds. Holdout: `governing-law`, `force-majeure`, `personal-data`, `assignment`. `HOLD_OUT_CELLS` är fortsatt `not_blind`.
5. Facit används bara i utvärderingen, aldrig som prompt-, index- eller söktext.

## 6. Två sökoperationer

Egenskapsindexet stöder två olika operationer, eftersom de löser olika uppgifter:

| Operation | Fråga | Resultat |
|---|---|---|
| **Ranked search** | ”Hitta de mest relevanta dokumenten” | Rankad dokumentlista, topp-k |
| **Property lookup** | ”Hämta alla avtal med `governing_law = Sweden`” | Samtliga dokument med egenskapen, paginerade, vidare till verifiering |

Lookup är den primära operationen för inventeringsfrågorna. Den trunkerar inte vid topp-k och pagineras (20 dokument/sida) med cursor och återupptagning utan dubbletter. Detta åtgärdar `governing-law`-fallet där topp-50 fysiskt inte kan rymma 75 dokument.

## 7. Utvärdering

### 7.1 Discovery

| Mått | Definition |
|---|---|
| Discovery@k (ranked) | Andel relevanta dokument identifierade vid dokumentbudget 10/20/50 |
| Lookup completeness | Andel gold-positiva dokument som looku­pen returnerar (ska vara oberoende av k) |
| Återfunna tidigare missade | Hur många av de 50 missade — särskilt `governing-law` 37 och `confidentiality` 4 — som nu identifieras |

### 7.2 Verification (tre nivåer)

För varje identifierad egenskap redovisas `GROUNDED`, `SUPPORTED`, `UNDECIDED`. `verified` kräver `SUPPORTED`. Polarity räknas: en negativ passage får inte verifiera en positiv egenskap.

### 7.3 Egenskapsrecall och precision

Verification ensamt räcker inte; en extractor kan hitta tio perfekta klausuler av hundra. Därför mäts egenskaperna i sig:

| Mått | Definition |
|---|---|
| Property recall | Andel gold-positiva dokument vars egenskap extraherades |
| Property precision | Andel extraherade positiva egenskaper som är gold-positiva |
| False positives | Extraherade positiva egenskaper som inte är gold-positiva |
| Missing properties | Gold-positiva dokument vars egenskap aldrig extraherades |

Unlabeled dokument räknas som `not_evaluated`, inte som negativa, om ingen negativ egenskaps-facit definierats.

### 7.4 Kostnad

- **Equal budget (ranked):** hybrid top-50 TextUnits (50 enheter) mot egenskapsindex som undersöker samma antal enheter (10 dokument × 5).
- **Lookup-kostnad:** paginering + verifieringsenheter per sida; B:s ingest-extraktion redovisas separat som en engångskostnad.
- Lokal CE@5 mäts för identifierade dokument för att bekräfta att evidenssteget fortfarande fungerar.

## 8. Jämförelsearmar

| ID | Vad |
|---|---|
| `hybrid_units_50` | Dagens hybrid top-50 (discovery-referens) |
| `dense_units_50` | Dense top-50 (referens) |
| `structure_doc` | Spår A, ranked + lookup |
| `jev_props` | Spår B, ranked + lookup |
| `structure_doc + jev_props` | Kombination |

## 9. Återanvändning

- `overgraph_ingest/doctags/` — `catalog.py`, `schema.py`, `extract.py`, `variant_a.py`, `source.py` (`validate_source`).
- `overgraph_ingest/doctype/` — dokumenttyp-taxonomi.
- `overgraph_ingest/coverage/proof.py`, `proof_gate`, `proof_logic` — polaritet/claim-form.
- `overgraph_ingest/retrieval/gold_map.py` — space-run-lokalisering.
- `overgraph_ingest/retrieval/discovery.py` — discovery- och equal-budget-mönstret.
- `overgraph_ingest/retrieval/bm25_paging.py` — cursor/paginering för lookup.

## 10. Implementation och leverabler

- Opt-in-kommando `--document-properties` med `--property-track {structure,jev,both}`, `--property-taxonomy PATH`, `--property-budget DOCS`, `--property-page-size`, `--property-output PATH`.
- Nya moduler: `retrieval/document_properties.py` (index, ranked + lookup, verification) och `doctags/properties.py` (taxonomi + extraktion).
- Output: ranked discovery, lookup completeness, tre-nivå verification, property recall/precision/false positives/missing, återfunna tidigare missade, kostnadstabell, manifest med taxonomihash och mappningshash.
- Fryst baseline endast via `--freeze-baseline`; befintliga filer skrivs aldrig över.
- Tester: taxonomihash, evidensförankring vs verifiering (tre nivåer), polarity, prompt/facit-separation, split-isolering, lookup-completeness + paginering, property recall/precision, ”ohängd egenskap räknas inte som verifierad”.

## 11. Beslutskriterier

| Utfall | Slutsats |
|---|---|
| Spår A återfinner många tidigare missade dokument till lägre kostnad, med hög `SUPPORTED`-andel | Struktur är en tillräcklig discoverysignal |
| Spår A räcker inte, men B återfinner dokumenten med god recall/precision och `SUPPORTED` | Egenskaper är rätt riktning; specificera ingest-lagring |
| B identifierar dokument men `GROUNDED` utan `SUPPORTED`, eller låg property recall | Egenskaper får inte bli `verified`; bygg inte vidare utan källkontroll och täckning |
| Varken A eller B återfinner `governing-law`-massan | Problemet är korpusens korta klausul + uttömmande genomsökning, inte discoverysignalen |

**Klart när vi kan säga:** hur många av de tidigare missade dokumenten A respektive B återfinner (ranked och via lookup), hur många identifieringar som är `SUPPORTED` respektive bara `GROUNDED`/`UNDECIDED`, och vad property recall/precision och kostnaden är jämfört med hybrid top-50. Produktion ändras inte av denna spec.
