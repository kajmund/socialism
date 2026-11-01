# Mutationsgrinden: klassificerad, inte räknad

En grön mutation siffra kan ljuga. B2:s differentialtest passerade varje mutation
eftersom det var en tautologi; B3:s tabell sade "7 av 7" när 7 missades. Därför
är grinden inte "kör `cargo-mutants` och kräv att alla mutationer dör". Den är:

> **Varje kritisk mutation är klassificerad som `detected`, `equivalent` eller
> `excepted` — med motivering — och en mutation vars utfall inte stämmer med
> klassificeringen fäller CI.**

## Vad klasserna betyder

| Klass | Krav | Varför |
| --- | --- | --- |
| `detected` | Mutationen **måste** göra minst ett test rött | Om den slutar fällas har testet som skulle fånga den ruttnat |
| `equivalent` | Mutationen **måste** lämna sviten grön, och motiveringen säger varför den inte kan ändra beteende | En äkta ekvivalent mutation ska inte kräva ett konstlat test |
| `excepted` | Mutationen lämnar sviten grön och vi accepterar det, med motivering | Vissa saker är uttryckligen inte kontrakt (t.ex. mänsklig feltext) |

Två saker gör grinden fail-closed:

1. **En mutation som inte kan appliceras fäller grinden.** En textersättning som
   inte matchar något skulle annars "passera" genom att inte göra något — exakt
   den felform som `drop_top_level_field` i runda 8 utgjorde.
2. **En `equivalent`/`excepted` som börjar fälla sviten fäller grinden.** Då är
   baslinjen inaktuell och påståendet om att mutationen är ofarlig är falskt.

Nya kritiska mutationer läggs in i `mutations/baseline.json` **med
klassificering**. Att lägga till en mutation utan klassificering är omöjligt:
manifestet är enda vägen in.

## Vad som körs

`scripts/check_mutations.py`:

1. kör paketets enhetstester och kräver grönt utgångsläge (annars kan grinden
   inte döma något);
2. skapar en **isolerad `git worktree`** i en temporär katalog med egen
   `CARGO_TARGET_DIR`, applicerar varje mutation där och kör testerna — den
   checkout som ska committas muteras aldrig. En låsfil räcker inte: den hindrar
   inte en oberoende `git add` från att se en muterad fil. Det hände en gång
   (commit `d74ace0b` bar med sig en mutation), och mekanismen ska göra den
   sortens misstag omöjligt, inte bara dokumentera det;
3. jämför utfallet med klassificeringen och skriver en tabell.

Grinden är offline och deterministisk: den kräver ingen extern tjänst och inget
nätverk, och den mäter samma sak lokalt som i CI. `cargo-mutants` kan senare
användas för att *föreslå* mutationer, men förslagen måste fortfarande
klassificeras i samma manifest — verktyget ersätter inte baslinjen.

## Utöka grinden

Lägg till en post i `mutations/baseline.json`:

```json
{
  "id": "kort-unik-beskrivning",
  "file": "crates/swe-native/src/operations.rs",
  "find": "exakt text som finns i filen",
  "replace": "ersättningen",
  "classification": "detected"
}
```

`detected` kräver inget mer; `equivalent` och `excepted` kräver `"reason"`.
Kör `python3 scripts/check_mutations.py` och lägg in resultatet i samma commit.

## Vad grinden redan hittat

När den infördes fällde den två av sina egna första mutationer:

- kärnan rapporterade `UNRESOLVED` för varje saknat behov i stället för den
  faktiska statusen — inget kärntest pinnade `MissingInput::status` (det gjorde
  bara referensdemon). Nytt kärntest: `the_gate_reports_why_each_input_is_missing`.
- en mutation som skulle förbjuda release av en avstämningspost träffade fel
  `match`-arm och var därför ekvivalent. Det syntes bara för att grinden kräver
  att en `detected`-mutation faktiskt fäller något.

Det är samma lärdom som `13-verification-standard.md` bygger på: verifieringen är
svagare än självförtroendet tills någon mäter den.
