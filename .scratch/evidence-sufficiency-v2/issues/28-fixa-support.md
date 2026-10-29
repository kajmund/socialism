# Fixa SUPPORT_INCOMPLETE i förenliga fall

Type: task
Status: resolved
Blocked by: 23

## Question

Varför verifieras inte relevance och factual_support för `compatible_periods`
och `compatible_entities`, trots att Jev korrekt bedömer paret som
SCOPE_DIFFERENCE?

- Diagnostiken visar `obligations_unverified`, independent support 0, komplett
  coverage och inga konflikter.
- Undersök om det är evidence screening, obligationströsklar, status/`found`,
  eller aggregeringslogiken som gör att stöd aldrig räknas.
- Åtgärda endast om orsaken är en bugg eller en felaktig tröskel; ändra inte
  beslutslogiken för att "få grönt" utan eget test.
- Mät mot B4c-arm D: de fyra false-insufficient ska minska utan nya
  false-sufficient eller försämrad coverage/konfliktupptäckt.
- A3-kontraktet och 40-parsbudgeten är oförändrade; SSR ingår inte.

Leverans: rotorsak, åtgärd (eller dokumenterat beslut att inte åtgärda), tester
och före/efter-artefakt.

## Answer

**Utredd 2026-10-23** (commit `73addf8c`). Resultatet är inte en
överförings- eller aggregeringsbugg: de fyra fallen var **off-topic-fixtures**.

### Spårning genom stegen

1. **Screening:** båda passageerna i `compatible_periods`/`compatible_entities`
   utvärderas; inga hoppas över.
2. **Exekvering:** `relevance` och `factual_support` körs. Jev svarar
   relevance 0,07–0,11 och support 0,05–0,10.
3. **Resultathantering:** giltiga bedömningar förs över till aggregationen; inga
   fel eller tappade rader.
4. **Aggregering:** obligationerna kräver relevance/support över tröskeln;
   med 0,1 är de korrekt overifierade.
5. **Tröskel:** inte för sträng. `short_sufficient` med on-topic-evidens får
   relevance 0,96/support 0,87 och verifierar båda obligationerna.

### Rotorsak

De fyra golden-fallen har planfrågan "Vilka avgöranden har tillämpat 36 §
avtalslagen?", medan evidensen handlar om `uppsägningstid`. Jev bedömer därför
korrekt att passagerna inte är relevanta/stödjande. `SCOPE_DIFFERENCE` säger
bara att två påståenden inte motsäger varandra i jämförd kontext — det bevisar
varken relevans eller faktiskt stöd. De fyra `insufficient`-besluten var alltså
**korrekta för den planfrågan**.

### Åtgärd

Ingen kod- eller tröskeländring. Samma kompatibla par byggdes om med
on-topic-frågan "Vilken uppsägningstid gäller?" och period-/entitetsproveniens:
alla fyra live-rep blir `sufficient` med `SUFFICIENT`, verifierad
relevance/factual_support och inga olösta konflikter
(`support-on-topic-v1.json`). De gamla fallen behandlas som ogiltigt facit för
den frågan och lämnas orörda i historiken.

**Slutsats:** stödkedjan fungerar när evidensen är relevant. Vi sänker inte
kraven för att få 26/26; nästa steg är ticket 29 (två stoppvillkor), därefter
SSR-förutsättningarna.
