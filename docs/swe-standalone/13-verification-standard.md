# Verifieringsstandard för SWE-kontrakten

Detta dokument är ett **granskningskrav**, inte en rekommendation. Det finns
därför att samma felform återkommit tre gånger: B1 hade en kringgåbar gate, B2
hade ett differentialtest som var en tautologi, och B3 hade både en journal utan
konsument och påståendet "7 av 7 mutationer fångas" när 7 missades. I runda 8
återkom tautologin i två nya differentialtester.

Mönstret är detsamma varje gång: **testet var grönt, men kunde inte ha varit
rött.** Ett grönt test som inte kan upptäcka det fel det påstår sig skydda mot är
värre än inget test, eftersom det köper falskt förtroende.

## Krav 1 — Oberoende vägar eller separat specifikation

Varje differentialtest måste visa att de två jämförda resultaten kommer från
**faktiskt oberoende exekveringsvägar**, eller jämföra mot en **separat förväntad
specifikation**.

Otillåtet:

```python
engine = swe_native.operation_gate("OP", required, states)
read = read_operation_gate(engine)          # läser engine-payloaden
assert read["missing"] == list(engine["missing"])   # jämför a med f(a)
```

Tillåtet:

```python
import swe_native, adapter

engine = swe_native.operation_gate("OP", required, states)
adapter_result = adapter.operation_gate(required, states)   # egen väg
assert adapter_result == {"satisfied": False, "conclusion": "INSUFFICIENT_EVIDENCE"}
assert engine["satisfied"] is False                          # separat specifikation
```

Regeln i praktiken:

- Jämför **aldrig** ett värde mot en funktion av samma värde.
- Skriv den förväntade specifikationen explicit i testet, inte som ett uttryck
  över det testet ska kontrollera.
- Om båda sidor delar kod (t.ex. samma normalisering) ska testet säga det, och
  det som ska bevisas är då gränssnittet, inte semantiken.

## Krav 2 — Minst en mutation per kritiskt test

Varje kritiskt test måste paras med **minst en mutation som bevisar att testet
kan upptäcka ett fel i det beteende det påstår sig verifiera**.

Ett mutationstest är bara giltigt om:

1. mutationen **faktiskt applicerades** (verifiera att källan ändrades — en
   textersättning som inte träffar är en tyst no-op och bevisar ingenting);
2. rätt test blir **rött**, inte bara något test;
3. resultatet återställs och den gröna baslinjen bekräftas.

Det räcker inte att ändra ett fält i testdata om ändringen aldrig når den
aktuella kodvägen. Om ett test tar bort ett fält ur en fil måste testet **bevisa
att fältet fanns** — annars prövar det en oförändrad fil.

## Krav 3 — En guard per sanning, inte en kopia per konsument

Om samma regel finns i två implementationer är det en bugg även när båda är
korrekta, eftersom de kan glida isär. Referensdemon fick därför inte behålla sin
egen `all_required`: den anropar kärnans grind och formaterar bara svaret.

**Känt undantag:** `swe-gym` bär fortfarande en egen `ALL_REQUIRED`-grind
(`crates/swe-gym/src/ops.rs` och `tools/measure_ops.py`). Den är spårad i
`05-gym-split` §9 G4 och ligger utanför extraktionsmålet. Kravet gäller därför
`crates/swe-native` och `crates/swe-reference`; gym-dubbletten ska stängas i G4,
inte döljas.

Konsekvens för testning: ett test som visar att kopian stämmer med originalet
låser in dubbletten. Testet ska i stället visa att konsumenten **anropar**
källan — t.ex. genom att mutation av källan får konsumentens test att falla.

Samma krav gäller **inom** en modul: när en regel behövs på två ställen ska den
lyftas ut, inte skrivas av. Dubblettregeln i kärnan ligger därför i
`ensure_unique_state`, som både `OperationSpec::gate` och `execute` anropar; en
mutation av den fäller båda konsumenternas tester.

## Krav 4 — Grinden får inte tyst välja

När en indata är tvetydig (samma behov med två statusar) ska gränssnittet
**avvisa** med ett typat fel som namnger problemet. Att välja "första träff"
gör svaret beroende av ordningen, och ordningsberoende i en grind är samma klass
av fel som en tautologi i ett test: resultatet ser deterministiskt ut men styrs
av något annat än semantiken.

Testet ska pröva **båda ordningarna** och kräva samma utfall.

## Krav 5 — Ett fel ska inte kunna förklä sig som ett svar

En felaktig anropssignal (t.ex. dubblerad statuspost) får inte rapporteras som
`INSUFFICIENT_EVIDENCE`. Det senare är en slutsats om världen; det förra är en
bugg i värden. Distinktionen ska finnas i typen, inte i en sträng.

## Tillämpning

Före varje granskningsrunda ska följande redovisas:

| Vad | Hur |
| --- | --- |
| Nya kritiska tester | lista, med vilken mutation som bevisar var och en |
| Mutationer som missades | alla, utan undantag — de är det mest värdefulla resultatet |
| Differentialtester | visa att sidorna är oberoende, eller namnge den separata specifikationen |
| Grön baslinje | bekräftad efter varje återställning |

En granskare som bara läser koden kan inte skilja ett test som kan falla från ett
som inte kan. Därför är mutationsbeviset en del av leveransen, inte ett extra
steg.
