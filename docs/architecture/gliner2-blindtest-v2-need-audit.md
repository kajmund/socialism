# Blindtest v2 — behovsrevision av de nio olösta behoven

**Status:** analys av den frysta blindtest v2-körningen. Ingen modell, prompt eller kontrakt
har ändrats; inga resultat har skrivits över. Artefakt:
`crates/swe-gym/benchmarks/blindtest_v2_need_audit.json` (redigerad: inga avtalstexter,
spann eller identifierande namn — repot är publikt).

## Varför den här revisionen

Blindtest v2 gav **7/16 lösta behov** (baslinje 2/16). En enda siffra blandar ihop två
olika frågor:

1. **Hur mycket förbättrar GLiNER2/JEV-kombinationen undersökningen?** 2 → 7 är 3,5×
   fler lösta behov — ett argument för att behålla kombinationen som valbar förmåga.
2. **Hur bra är undersökningsförmågan i sig?** 9/16 olösta är ett argument för att
   extraktionsproblemet inte är färdiglöst — och för att nästa investering inte
   nödvändigtvis ska ligga i GLiNER2.

Den här revisionen klassificerar de nio olösta behoven efter **vilken förmåga som
faktiskt saknades**, med bevis från det frysta materialet och källdokumenten.

## Metod

- Varje behov rekonstruerades ur fryst facit + kandidatlistor + JEV-svar: vilka spann som
  föreslogs, vilka JEV-bedömningar de fick, vilken operativ roll de fick och vilka
  evidensposter som till slut blev VERIFIED/AMBIGUOUS/REJECTED.
- För varje behov kontrollerades om det efterfrågade sakförhållandet **överhuvudtaget
  står i dokumentet** (despacead delsträngskontroll mot den extraherade texten).
- Varje olöst fall fick en **första förlustpunkt** i pipelinen (den komponent som först
  tappade evidensen) samt bidragande lager.
- Inga motåtgärder har körts; motfaktiska uppskattningar är hypoteser, inte mätningar.

### Pipelinen som lager

`retrieval_context` (vilken TextUnit/klausul som skannas) → `candidate_generation`
(GLiNER2/extraktorn föreslår spann) → `verification` (JEV avgör betydelsen) →
`contract_role` (E3 operativ roll) / `contract_aggregation` (E2 kanonisering,
konkurrerande värden) → `need_model` (ett värde per behov) → `material_preprocessing`
(extraktionens whitespace-artefakter).

## Resultat: 9 olösta behov

| Fall | Typ | Utfall | Första förlustpunkt | Bidragande | Lösbarhet |
|---|---|---|---|---|---|
| v2-pm-01 | NOTICE_PERIOD | olöst | candidate_generation | contract_role | efter verktygsutbyggnad |
| v2-pm-02 | LIABILITY_CAP | olöst | contract_role | — | med befintliga verktyg |
| v2-pm-03 | MONEY | ambiguous | candidate_generation | contract_aggregation | efter verktygsutbyggnad |
| v2-pm-05 | PERIOD | olöst | material_preprocessing | verification | med befintliga verktyg |
| v2-pm-07 | PARTY | olöst | verification | need_model, candidate_generation | kräver ny förmåga |
| v2-sv-01 | PARTY | ambiguous | need_model | — | kräver ny förmåga |
| v2-sv-03 | DATE | olöst | material_preprocessing | verification | med befintliga verktyg |
| v2-if-05 | PARTY | olöst | retrieval_context | verification | med befintliga verktyg |
| v2-if-06 | PARTY | olöst | retrieval_context | candidate_generation | med befintliga verktyg |

### Vad klassificeringen betyder

- **Alla 16 behov har svaret uttalat i källdokumentet** — inget behov i v2 är
  källmässigt omöjligt, och inget kräver extern rättskälla. Det gör att ett korrekt
  avstående inte är relevant för v2; den siffran mäts bättre på v1: s LAS-fall (där
  dokumentet inte innehåller svaret), som kedjan korrekt avstod från.
- **Två tydliga kluster är extraktions- och materialnära, inte GLiNER2-nära:**
  `material_preprocessing` (whitespace/radbrytningar i spann) och `candidate_generation`
  (ofullständiga spann som konkurrerar med hela värdet). De två materialfallen och
  delspannsfallet är sannolikt billiga att lösa med befintlig normalisering/postprocess.
- **Partbehoven är den stora strukturella luckan:** 0/4. Två av dem kräver ett
  **flervärdesmodell** för behov (en avtalspart är inte alltid ett värde), en kräver
  bättre **kontextfönster** (JEV bedömer en för tunn klausul), och en kräver
  verifieringsåterhämtning. Det är inte samma sorts fel som en missad tidsperiod.
- **Ett fall är en rollklassificering** (`contract_role`: rätt spann, JEV YES, men E3:s
  närmaste-kue-regel gav en annan roll och exkluderade evidensen). Det är en
  kontraktsregel som behöver robusthet, inte mer modell.

## De två mätten

| Mått | Värde |
|---|---|
| Andel korrekt lösta av faktiskt lösbara behov | **7/16 = 44 %** (alla 16 har svaret i dokumentet) |
| Andel korrekta avståenden när behoven inte är lösbara | **n/a i v2** (0 olösliga); referens: v1 LAS-fall 1/1 korrekt avstående |

Det första mättet är det ärliga för v2: eftersom källfrågan inte utesluter något fall blir
det 7/16. När ett dokumentset innehåller behov som **inte** kan lösas med tillgängliga
källor blir det andra mättet avgörande — annars belönas en kedja som gissar.

## Motfaktiska hypoteser (inte mätningar)

Uppskattning per enskild åtgärd, från den frysta spårningen:

| Åtgärd | Förväntat antal ytterligare lösta | Fall |
|---|---|---|
| Whitespace-normalisering | +2 | v2-pm-05, v2-sv-03 |
| Spann-gräns-sammanslagning | +1 | v2-pm-03 |
| Roll-kue-korrigering | +1 | v2-pm-02 |
| Behovsanpassat kontextfönster | +2 | v2-if-05, v2-if-06 |
| Flervärdesmodell för behov | +1 | v2-sv-01 |
| Alla åtgärder kombinerat | upp till +9 (16/16) | hypotes — kräver ablationsexperiment |

Dessa är **inte** mätningar och får inte citeras som resultat. De anger bara var nästa
experiment bör mäta.

## Nästa experiment: förmågeattribution, inte GLiNER2-optimering

Per protokollets princip 5 blir varje åtgärd en **ny version** med egna artefakter.
Förslaget är en ablationsstudie på samma 16 frysta fall:

- **M0** fryst kedja (7/16, referens).
- **M1** + whitespace-normalisering i materialet.
- **M2** + spann-gräns-sammanslagning före aggregering.
- **M3** + robustare rollklassificering (alternativt: låt behovet deklarera rollen
  striktare).
- **M4** + behovsanpassat kontextfönster (större TextUnit för verifiering).
- **M5** + flervärdesmodell för behov (parter m.fl.).
- **M6** + verifieringsåterhämtning (t.ex. andra JEV-promptversionen för entiteter).

Rapportera per åtgärd: lösta behov, **andel korrekt lösta av lösbara**, **andel korrekta
avståenden** (kräver ett dokumentset med verkligt olösliga behov), kostnad i inferenser
och JEV-anrop, samt svarsnivåkontamination enligt D10-proceduren. Ingen åtgärd får
aktiveras brett förrän den visat sig på ofrysta dokument.

## Slutsats för integrationsbeslutet

GLiNER2 som **avstängd, valbar** förmåga står kvar: den ger 3,5× fler lösta behov på
osedda avtal. Men det större beslutet — om Socialisms Investigation-lager är tillräckligt
generellt för verkliga avtal — är **inte** besvarat av 7/16. Den här revisionen visar att
nästa investering ligger i undersökningsförmågan (kontext, spann-gränser, rollrobusthet,
behovsmodell), inte i ytterligare GLiNER2- eller JEV-finjustering.
