# Licensbeslut (2026-11-01)

## Beslut

| Fråga | Beslut |
| --- | --- |
| Licens | **MIT OR Apache-2.0** (dubbel) |
| Rättighetsinnehavare | `Copyright (c) 2026 Erik Fremred` |
| AI-agentförfattarskap | dokumenteras i `06-extraction-plan.md` |
| Yta | **endast extraktionsmålet**: `crates/swe-native`, `crates/swe-budget`, `crates/swe-reference`, `python/**`, `contracts/**` |
| Socialism-repot i övrigt | förblir `UNLICENSED` (Research, frontend, word-addin m.m.) |
| Synlighet | **publikt** repository |
| Repo | **`kajmund/swe`** |
| crates.io | `swe-native`, `swe-budget` (båda lediga vid kontroll 2026-11-01) |
| PyPI-distribution | **`swe-engine`** — `swe` är upptaget; importnamnet är fortfarande `swe` |
| Publicering | `publish = false` tills crates.io/PyPI-namnen är verifierat lediga |

## Vad som ligger i trädet nu

- `LICENSE-MIT` och `LICENSE-APACHE` i `crates/swe-native`, `crates/swe-budget`,
  `crates/swe-reference` och `python/`.
- `license = "MIT OR Apache-2.0"` i de tre `Cargo.toml`.
- `license = { text = "MIT OR Apache-2.0" }` i `python/pyproject.toml`.
- Licenstexterna är hämtade från den kanoniska Apache-2.0- och MIT-texten som
  levereras i cargo-registret, med vår egen copyright-rad i MIT-filen —
  inte avskrivna från minnet.

Filerna ligger i varje paketkatalog, inte i repo-roten, eftersom repo-roten
fortfarande innehåller kod som **inte** licensieras. När SWE flyttas blir
`LICENSE-MIT`/`LICENSE-APACHE` rotfiler i det nya repot.

Synligheten är en förutsättning för licensen, inte en detalj: ett publikt repo
**distribuerar** koden, och då gäller MIT/Apache-2.0:s krav på att licens- och
upphovsrättstexter följer med. Därför blir `THIRD-PARTY-NOTICES` och licensgrinden
inte valfria dekorationer utan en del av publiceringen. Ett publikt repo innebär
också att historiken syns — därav att AI-agentförfattarskapet är dokumenterat i
`06` och inte bara går att hitta i `git log`.

## Namn — kontrollerat mot registren

- **crates.io:** `swe-native` och `swe-budget` finns inte (HTTP 404 vid kontroll
  2026-11-01). Namnen kan behållas.
- **PyPI:** distributionen `swe` är **upptagen** av ett annat projekt (svensk-engelsk
  ordbok, `bjesus/swe`). Därför heter distributionen `swe-engine` (också ledigt vid
  kontrollen), medan **importpaketet fortfarande heter `swe`** — det påverkar inte
  någon kod, bara paketets namn i `python/pyproject.toml`, backendens beroende och
  lockfilerna.
- **Repo:** `kajmund/swe`, publikt.

En kollision som den här är exakt varför `publish = false` står kvar tills namn,
licens och äganderätt är verifierade.

## Medvetet uppskjutet till PR 4

- `THIRD-PARTY-NOTICES`: MIT och Apache-2.0 kräver att licens- och
  upphovsrättstexter följer med vid distribution av binärer/wheels. 41 Rust- och
  7 Python-beroenden är permissiva; `unicode-ident` är
  `(MIT OR Apache-2.0) AND Unicode-3.0` och kräver sin Unicode-text.
  Genereras lämpligen med `cargo-about`/`cargo-deny` när det nya repot finns.
- Licensgrind i CI (t.ex. `cargo-deny` med tillåten lista) — samma skäl.
- PEP 639 `license-files` i `pyproject.toml`; nuvarande `license = { text = ... }`
  fungerar med alla byggare men får inte med sig licenstexterna i hjulet
  automatiskt.
- `publish = false` → `true` först när namn och äganderätt är verifierade.

## Grund för beslutet

Fakta från licensutredningen (`08 §7.14`):

- **Ingen LICENSE-fil har någonsin funnits** i repots 1 459 commits; alla crates
  angav `UNLICENSED` och `publish = false`; inga SPDX-identifierare eller
  copyright-huvuden fanns. MIT/Apache är därför ett positivt beslut av
  rättighetsinnehavaren, inte ett klargörande av något som redan gällde.
- **Ingen kopierad tredjepartskod** hittades i extraktionsmålet. Enda
  härledningen är intern (`swe-budget` är en 0-rads flytt av `swe-gym`-ledgern,
  `af15a396`).
- **Alla 48 beroenden är permissiva**; ingen copyleft, inga NOTICE-filer, inga
  git-beroenden. `unicode-ident` är det enda `AND`-fallet.
- **7 commits på målvägarna är författade under `Cursor Agent`**, inklusive
  kärnan och SWD-schemat — dokumenterat i `06`, eftersom en extern läsare
  annars hittar det i `git log`.
- **Rättighetsinnehavaren har bekräftats av ägaren** som personligt ägande av
  koden; detta är den enda punkten i B4 som inte kunde verifieras tekniskt.
