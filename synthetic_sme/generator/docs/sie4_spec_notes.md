# SIE4 (SIE-formatet typ 4) — technical notes for exporter + round-trip reader/validator

Status: researched from the **official primary sources** on 2026-10-18 (sie.se was reachable).
All statements in sections 1–8 are taken directly from the official specification PDF(s) unless marked otherwise.

## Sources (primary)

| Source | URL | Publication date | Confidence |
|---|---|---|---|
| SIE-filformat spec, **Utgåva 4C** (Swedish, 40 pp.) — **the current official spec** | https://sie.se/wp-content/uploads/2026/02/SIE_filformat_ver_4C_2025-08-06.pdf | 2025-08-06 | High (official) |
| SIE file format spec, **Version 4C, English translation** (41 pp.) | https://sie.se/wp-content/uploads/2026/09/SIE_filformat_ver_4C_250806_ENGLISH.pdf | 2025-08-06 (uploaded 2026-09) | High (official) |
| Spec index page (links, sample file, SIE 5) | https://sie.se/format/ | fetched 2026-10-18 | High |
| Official SIE4 sample file, `SIE4 Exempelfil.SE` (Visma Administration 2000 export, 4080 lines) | https://sie.se/wp-content/uploads/2024/01/SIE4-Exempelfil-Sample-file-1.zip | file dated 2024-01-08 | High (official sample) |
| Official online test service | https://sietest.sie.se/ (linked from https://sie.se/ as "Testa dina SIE-filer") | fetched 2026-10-18 | High that it exists; UI is a JS SPA, exact check list not published |
| Fortnox import & troubleshooting guides | https://support.fortnox.se/produkthjalp/bokforing/importera-sie-fil , https://support.fortnox.se/produkthjalp/bokforing/felsokningsguide-sie-fil | fetched 2026-10-18 | High for Fortnox-specific behavior |
| Visma.net "Hantering av SIE-filer" (training doc, 2017) | https://community.visma.com/legacyfs/online/sweden_global_images/Visma%20Software%20SE/Visma.net/Dokument/SIE-filer.pdf | 2017-08-28 | Medium (old, product-specific) |

Notes on versioning: the **document revision** is 4C (2025-08-06), first revision since 4B (2008-09-30). The file format itself is unchanged — 4C only clarifies texts (see ch. 13 of the spec). The Swedish PDF's internal metadata title says "...4C_2025-08-06 **DRAFT**", but sie.se links it as the current official spec. All examples in 4C use BAS2025 accounts. A `#SIETYP 4` file is unaffected by which doc revision it was written against.

---

## 1. Encoding, line endings, #FORMAT

- **Character set: IBM PC 8-bit extended ASCII = codepage 437 (CP437). Only.** Spec 5.8: "Teckenrepertoaren i filen ska vara IBM PC 8-bitars extended ASCII (Codepage 437)". The `#FORMAT` tag declares it, and PC8 is the *only* allowed value (spec #FORMAT: "Tills vidare tillåter standarden endast IBM Extended 8-bit ASCII (PC8 - codepage 437)").
  - So `å` = 0x86, `ä` = 0x84, `ö` = 0x94, `Å` = 0x8F, `Ö` = 0x99 (not UTF-8, not ISO-8859-1). Byte-inspection of the official sample confirms CP437 (`Kaffebröd` is `Kaffebr` + 0x94 + `d`), **but** the sample also contains at least one stray ISO-8859-1-style byte (0xF6 for "ö" in the `#FNR` path, which renders as `F÷retag` under CP437) — even the official sample is not 100% CP437-clean. Readers should tolerate this; exporters should emit pure CP437.
  - **Exporter rule:** encode output as CP437. If a character has no CP437 mapping, replace it (do not emit UTF-8 bytes — strict validators flag bytes >0x7F that decode to nothing).
  - **Reader/validator rule:** decode as CP437 when `#FORMAT PC8` is present. In the wild many exporters write UTF-8/latin-1 anyway; a *lenient* reader may sniff, but the spec says CP437 and the official test service is likely strict.
- **Line endings** (5.5): every record must end with a line feed (ASCII 10). A carriage return (ASCII 13) *before* the LF is allowed but not required. (Official sample uses CRLF.)
- **Blank lines** (5.6): allowed anywhere; importers must ignore them.
- **Field separators** (5.7): one or more spaces; tabs (ASCII 9) also count as spaces. Any field may be wrapped in double quotes (ASCII 34); quotes are required **only when the field contains spaces**. A literal `"` inside a field must be escaped with a backslash (ASCII 92). Control characters (ASCII 0–31 and 127) may not occur inside a text string.
- **Braces** (5.4): sub-records (e.g. `#TRANS` rows of a `#VER`) are enclosed in `{` ... `}`, each brace **alone on its own line**.

```sie
#FORMAT PC8
```

---

## 2. Section order and mandatory/optional records

### Global ordering rules (5.11–5.13)

All records belong to four groups, which must appear **in this exact order**:

1. **Flag record** — `#FLAGGA`
2. **Identification records** — `#PROGRAM`, `#FORMAT`, `#GEN`, `#SIETYP`, `#PROSA`, `#FTYP`, `#FNR`, `#ORGNR`, `#BKOD`, `#ADRESS`, `#FNAMN`, `#RAR`, `#TAXAR`, `#OMFATTN`, `#KPTYP`, `#VALUTA`
3. **Chart of accounts** — `#KONTO`, `#KTYP`, `#ENHET`, `#SRU`, `#DIM`, `#UNDERDIM`, `#OBJEKT`
4. **Balance records / voucher records** — `#IB`, `#UB`, `#OIB`, `#OUB`, `#RES`, `#PSALDO`, `#PBUDGET`, `#VER` (+ `#TRANS`/`#RTRANS`/`#BTRANS` inside), `#KSUMMA`

- Order *within* a group is free **unless** a record spec says otherwise. Two such constraints exist: `#KTYP`/`#ENHET` must come after the corresponding `#KONTO`; vouchers must be in ascending voucher number order within each series (see §4).
- Importer must ignore unknown tags (7.1); a file may only contain tags defined by the SIE standard (7.2); unknown *trailing fields* at the end of a known record must be tolerated (7.3).

### Mandatory per file type (ch. 6 table) — columns: type 1 / 2 / 3 / 4I / 4E

`●` mandatory, `○` optional, `–` **must not occur** in that file type. `†` = records for both current year (0) and previous year (−1) if available. `❖` = for type 3, dims need not be declared if they match the standard/reserved dimensions.

| Tag | 1 | 2 | 3 | 4I | 4E | |
|---|---|---|---|---|---|---|
| `#FLAGGA` | ● | ● | ● | ● | ● | |
| `#PROGRAM` | ● | ● | ● | ● | ● | |
| `#FORMAT` | ● | ● | ● | ● | ● | |
| `#GEN` | ● | ● | ● | ● | ● | |
| `#SIETYP` | ○ | ● | ● | ● | ● | (if absent: assume type 1) |
| `#PROSA` | ○ | ○ | ○ | ○ | ○ | |
| `#FTYP` | ○ | ○ | ○ | ○ | ○ | |
| `#FNR` | ○ | ○ | ○ | ○ | ○ | |
| `#ORGNR` | ○ | ○ | ○ | ○ | ○ | |
| `#BKOD` | ○ | ○ | ○ | **–** | ○ | forbidden in 4I |
| `#ADRESS` | ○ | ○ | ○ | ○ | ○ | |
| `#FNAMN` | ● | ● | ● | ● | ● | |
| `#RAR` | ●† | ●† | ●† | ○ | ●† | optional in 4I |
| `#TAXAR` | ○ | ○ | ○ | ○ | ○ | |
| `#OMFATTN` | – | ● | ● | **–** | ○ | forbidden in 4I |
| `#KPTYP` | ○ | ○ | ○ | ○ | ○ | |
| `#VALUTA` | ○ | ○ | ○ | ○ | ○ | |
| `#KONTO` | ● | ● | ● | ○ | ● | |
| `#KTYP` | ○ | ○ | ○ | ○ | ○ | |
| `#ENHET` | ○ | ○ | ○ | ○ | ○ | |
| `#SRU` | ● | ● | ○ | ○ | ○ | |
| `#DIM` | – | – | ●❖ | ○ | ○ | |
| `#UNDERDIM` | – | – | ●❖ | ○ | ○ | |
| `#OBJEKT` | – | – | ●❖ | ○ | ○ | |
| `#IB` | ●† | ●† | ●† | **–** | ●† | see IB/UB rule below |
| `#UB` | ●† | ●† | ●† | **–** | ●† | see IB/UB rule below |
| `#OIB` | – | – | ●† | – | ○ | |
| `#OUB` | – | – | ●† | – | ○ | |
| `#RES` | ●† | ●† | ●† | **–** | ●† | |
| `#PSALDO` | – | ● | ● | – | ○ | |
| `#PBUDGET` | – | ● | ● | – | ○ | |
| `#VER` | – | – | – | ○ | ○ | obviously the point of 4I |
| `#TRANS` | – | – | – | ○ | ○ | |
| `#RTRANS` | – | – | – | ○ | ○ | |
| `#BTRANS` | – | – | – | ○ | ○ | |
| `#KSUMMA` | ○ | ○ | ○ | ○ | ○ | |

### IB/UB special rule (5.16–5.18)

- `#UB` for the **current year (0)** must always exist.
- Either `#UB` for the **previous year (−1)** or `#IB` for the **current year (0)** must exist (recommend both).
- `#IB` for the previous year is entirely optional.
- Zero-balance records may be omitted ("saldoposter med nollbelopp ej behöver skrivas"); a newly started company with no opening balances may legitimately have no `#IB` rows.

### Consequences for a standard SIE4 export (4E)

Mandatory: `#FLAGGA`, `#PROGRAM`, `#FORMAT`, `#GEN`, `#SIETYP 4`, `#FNAMN`, `#RAR` (year 0 and −1), `#KONTO` (all used accounts), `#IB`/`#UB`/`#RES` for both years (per the IB/UB rule). Everything else is optional. The official sample includes `#ORGNR`, `#ADRESS`, `#TAXAR`, `#VALUTA SEK`, `#KPTYP EUBAS97`, `#KTYP`, `#SRU`, `#DIM`/`#OBJEKT` but **no** `#PSALDO`/`#PBUDGET`/`#OIB`/`#OUB`/`#ENHET`/`#KSUMMA`/`#RTRANS`/`#BTRANS`.

### Consequences for a SIE4 import file (4I)

Mandatory: `#FLAGGA`, `#PROGRAM`, `#FORMAT`, `#GEN`, `#SIETYP 4`, `#FNAMN`, plus `#VER`/`#TRANS` (marked ○ in the table but that *is* the content). `#RAR` optional (still recommended). `#KONTO`/`#OBJEKT` optional — if omitted, the accounts/objects are assumed to already exist in the receiving program; declaring them lets the importer create them. **Forbidden in 4I:** `#BKOD`, `#OMFATTN`, `#IB`, `#UB`, `#OIB`, `#OUB`, `#RES`, `#PSALDO`, `#PBUDGET`, and per the table all of them are "–" for 4I. (Note: the spec's own table forbids saldo records in 4I; vouchers with no balance context.)

### File naming (5.1–5.2)

Free, but recommended: `.SE` for exports (types 1/2/3/4E), **`.SI` for 4I import files**; recommended names `FAKT.SI` (invoicing), `LEVR.SI` (supplier ledger), `LÖN.SI` (payroll); directory `\SIE`.

---

## 3. Header tags (identification group)

Exact formats from ch. 11, with official examples:

| Tag | Format | Example(s) | Notes |
|---|---|---|---|
| `#FLAGGA` | `#FLAGGA x` | `#FLAGGA 0` | **First record.** Writer sets 0; importer overwrites with 1 after successful import (prevents double import). The official Visma sample ships with `#FLAGGA 1` — validators should NOT reject flag=1. |
| `#PROGRAM` | `#PROGRAM programnamn version` | `#PROGRAM "Visma Compact" 5.1` | mandatory |
| `#FORMAT` | `#FORMAT PC8` | `#FORMAT PC8` | mandatory; PC8 only |
| `#GEN` | `#GEN datum sign` | `#GEN 20250518 AN` | mandatory; date `YYYYMMDD` required, signature optional (name/signature/userid of generating person/process) |
| `#SIETYP` | `#SIETYP typnr` | `#SIETYP 4` | mandatory for type 4; absent ⇒ type 1 |
| `#PROSA` | `#PROSA text` | `#PROSA "Exporterat med Visma Compact 080512"` | optional free comment |
| `#FTYP` | `#FTYP företagstyp` | `#FTYP AB` | optional; codes: `AB E HB KB EK KHF BRF BF SF I S FL BAB MB SB BFL FAB OFB SE SCE TSF X` (X = other). Used with `#TAXAR` to pick the SRU code set. |
| `#FNR` | `#FNR företagsid` | `#FNR Kalles` | optional internal company id |
| `#ORGNR` | `#ORGNR orgnr förvnr verknr` | `#ORGNR 556334-3689 1` | optional; org number **must have hyphen after 6th digit**; förvnr/verknr optional, omitted if unknown |
| `#BKOD` | `#BKOD SNI-kod` | `#BKOD 82300` | optional (SNI/NACE industry code); **forbidden in 4I** |
| `#ADRESS` | `#ADRESS kontakt utdelningsadr postadr tel` | `#ADRESS "Sven Svensson" "Box 21" "211 20 MALMÖ" "040-123 45"` | optional |
| `#FNAMN` | `#FNAMN företagsnamn` | `#FNAMN "Målerifirman Axelsson & Johnsson AB"` | mandatory; legal name |
| `#RAR` | `#RAR årsnr start slut` | `#RAR 0 20250101 20251231` / `#RAR -1 20240101 20241231` | mandatory (4E); `årsnr` = 0 current year, −1 previous, further comparison years −2, −3 …; dates `YYYYMMDD`. **Only one chart of accounts exists in the file (year 0); all comparison-year data must be normalized onto it.** |
| `#TAXAR` | `#TAXAR år` | `#TAXAR 2025` | optional; taxation year (`YYYY`) the `#SRU` codes refer to |
| `#OMFATTN` | `#OMFATTN datum` | `#OMFATTN 20250630` | date through which period balances run; **mandatory when exporting period balances** (type 2/3); optional in 4E, forbidden in 4I |
| `#KPTYP` | `#KPTYP typ` | `#KPTYP EUBAS97` | optional chart-of-accounts type: `BAS95`, `BAS96`, `EUBAS97`, `NE2007`; absent ⇒ assume BAS95; `BAS2xxx` (e.g. BAS2025) is handled as `EUBAS97` |
| `#VALUTA` | `#VALUTA valutakod` | `#VALUTA NOK` | optional; ISO 4217; absent ⇒ assume SEK |

### Chart-of-accounts group

```sie
#KONTO 1510 "Kundfordringar"      ; kontonr must be numeric; export ALL used accounts
#KTYP 1510 T                      ; optional; T=tillgång(asset) S=skuld(liability) K=kostnad(cost) I=intäkt(revenue)
                                  ; must appear AFTER the #KONTO it refers to; absent ⇒ type per BAS standard
#ENHET 4010 liter                 ; optional unit for quantity on account; must follow #KONTO
#SRU 1910 7214                    ; SRU code mapping; several rows per account allowed; only mandatory in types 1-2
```

---

## 4. Verifikation (voucher) structure

```sie
#VER serie vernr verdatum vertext regdatum sign
{
#TRANS 1910 {} -1000.00
#TRANS 2640 {} 200.00
#TRANS 6250 {} 800.00
}
```

### `#VER` — format `#VER serie vernr verdatum vertext regdatum sign`

1. Must always be followed by a number of `#TRANS` (etc.) rows inside braces (braces alone on their own lines).
2. `vertext` optional.
3. `regdatum` = date the voucher was generated/registered (used in processing history); optional.
4. `serie`: letters from A onward, or digits from 1, or an alphanumeric string (e.g. `LEV1`). Importers must handle all variants. In 4I files, serie and/or vernr may be **empty** — written as `""` — and the receiving program assigns them.
5. `vernr`: numeric voucher number.
6. All numbered vouchers within one series must appear in **ascending vernr order** in the file.
7. `sign` optional (name/signature/userid of person/process that created/last edited it).

Examples: `#VER A 567 20251216 "Kontant lön" 20251216 AN` · `#VER "" "" 20250101 "Porto"`

### `#TRANS` — format `#TRANS kontonr {objektlista} belopp transdat transtext kvantitet sign`

1. `transdat` (transaction date) and `transtext` optional; missing transdat ⇒ use the voucher's `verdatum`.
2. Only allowed as a sub-record of `#VER`.
3. **A voucher must balance: the sum of all transaction amounts within one voucher must be zero.**
4. `kvantitet` optional; normally same sign as amount (plus = debit, minus = credit).
5. `sign` optional (name/signature/userid).

Example: `#TRANS 7010 {"1" "456" "7" "47"} 13200.00`

### `#RTRANS` (added row) and `#BTRANS` (removed row) — SIE4-only, added in the 4B revision

Same field layout as `#TRANS`.

- **`#RTRANS`:** an *added* transaction row. For backward compatibility with pre-2008 readers, **every `#RTRANS` row must be immediately followed by an identical `#TRANS` row**:

```sie
#RTRANS 1910 { } 200.00
#TRANS 1910 { } 200.00
```

Readers that don't handle `#RTRANS`/`#BTRANS` must ignore those rows and read the following `#TRANS` instead. Readers that do handle `#RTRANS` must **ignore the following `#TRANS` row** (it is a duplicate). Net effect: the row is added once.

- **`#BTRANS`:** a *deleted* (struck) row. No companion `#TRANS`. A row that was first added (`#RTRANS`) and later deleted is exported as **`#BTRANS` only** (4C clarification):

```sie
#TRANS  1910 { } -1000.00
#TRANS  2640 { }  200.00
#BTRANS 6110 { }  800.00
#RTRANS 6250 { }  800.00
#TRANS  6250 { }  800.00
```

Net result after full handling: 1910 −1000, 2640 +200, 6110 +800, 6250 +800 (the `#RTRANS`/`#TRANS` pair contributes one +800 row). The official sample file contains **no** `#RTRANS`/`#BTRANS` — they are optional.

### Sign conventions (debit/credit)

- Positive = debit, **negative = credit** everywhere (`#TRANS`, `#RTRANS`, `#BTRANS`, and all saldo records). This is the #1 round-trip bug source: a credit entry on 1910 (bank) is written `-195.00`, and a revenue credit balance is negative.
- The official sample's first voucher: `#TRANS 1910 {} -195.00`, `#TRANS 2641 {} 20.88`, `#TRANS 7690 {} 174.12` — sums to 0.00.

---

## 5. Amount format rules (5.9)

- Decimal separator: **dot** (ASCII 46). Max **two** decimals. Decimals may be omitted entirely.
- **No thousands separators**, no plus sign; a minus sign goes before the amount.
- No upper size limit — importers must check their own limits.
- Examples: `1234.50`, `-1000.00`, `350000` (ok, no decimals).

## Date formats (5.10)

- Dates are **always `YYYYMMDD`** (8 digits, no separators).
- Periods (in `#PSALDO`/`#PBUDGET`) are `YYYYMM`.
- `#TAXAR` year is `YYYY`.

---

## 6. Dimensions & objects (`#DIM`, `#UNDERDIM`, `#OBJEKT`)

```sie
#DIM 1 "Kostnadsställe"      ; simple dimension: dimnr + name
#DIM 6 "Projekt"
#UNDERDIM 2 "Kostnadsbärare" 1   ; sub-dimension: dimnr name superdimension
#OBJEKT 1 "0123" "Serviceavdelningen"   ; dimnr objectcode objectname
```

- **Reserved dimension numbers** (8.17): `1` = cost center / result unit; `2` = cost bearer (must be a sub-dimension of 1); `3–5` reserved; `6` = project; `7` = employee; `8` = customer; `9` = supplier; `10` = invoice; `11–19` reserved; `20+` free for own use. If only reserved numbers are used, the declarations themselves may be omitted (that is the `❖` in the table).
- **Object list on `#TRANS` rows** (8.21): pairs of dimension number and object code, only the relevant ones; empty braces `{}` when none.

```sie
#TRANS 7010 {"1" "456" "7" "47"} 13200.00
#TRANS 1910 {} -13200.00
```

- **Hierarchical dimensions** (8.10–8.14): balances are exported separately for the parent object rows and the child object rows; child object codes are the **concatenation** of parent + child code. Only the sub-dimension code appears in the object list on the child's place; the parent object must also always be present in the object list (8.23). Uniform code length is assumed — if codes vary in length, pad (the spec shows padding with `¤`).
- On `#OBJEKT` rows object codes/names may be quoted; the sample file writes them unquoted when they contain no spaces.
- Saldo rows on objects: `#PSALDO 0 202501 4010 {20 "01"} 49655.00` (account-level and object-level rows both exported in type 3).

---

## 7. Balance records

| Tag | Format | Example | Notes |
|---|---|---|---|
| `#IB` | `#IB årsnr konto saldo kvantitet` | `#IB 0 1930 23780.78` | credit = negative; quantity optional, same sign |
| `#UB` | `#UB årsnr konto saldo kvantitet` | `#UB 0 2440 -2380.39` | credit = negative |
| `#RES` | `#RES årsnr konto saldo kvantitet` | `#RES 0 3011 -23780.78` | result accounts; credit = negative |
| `#OIB` | `#OIB årsnr konto {dimensionsnr objektnr} saldo kvantitet` | `#OIB 0 1510 {8 "12345"} 23780.78` | object opening balance (type 3) |
| `#OUB` | `#OUB årsnr konto {dimensionsnr objektnr} saldo kvantitet` | `#OUB 0 1510 {8 "12345"} 23780.78` | object closing balance (type 3) |
| `#PSALDO` | `#PSALDO årsnr period konto {dimensionsnr objektnr} saldo kvantitet` | `#PSALDO 0 202508 1910 { } 1243.50 123` | period change; `period` = YYYYMM; type 2: no object spec; type 3: both account-level and object-level rows |
| `#PBUDGET` | `#PBUDGET årsnr period konto {dimensionsnr objektnr} saldo kvantitet` | `#PBUDGET 0 202501 3011 {} -1243.50 -415` | period budget; credit = negative; quantity same sign |

- `årsnr`: 0 current, −1 previous, further comparison years −2, −3 …
- Quantity field is optional in all of them; unit declared via `#ENHET`.
- **Fortnox import note** (vendor doc): budget import expects **revenue accounts negative, cost accounts positive** in `#PBUDGET 0` rows (opposite of Fortnox's own manual entry UI).

---

## 8. Date and signature formats

- All dates `YYYYMMDD` (voucher date, registration date, transaction date, `#GEN` date, `#RAR` start/slut, `#OMFATTN`).
- Signature fields (`#GEN sign`, `#VER sign`, `#TRANS`/`#RTRANS`/`#BTRANS` `sign`): free text — name, initials, or user id of the person/process; **may be omitted entirely** (trailing field; see §12 rule below).

---

## 9. Official validation/test service

- **URL: https://sietest.sie.se/** — the official automatic online test service, linked from the sie.se front page ("Testa dina SIE-filer … automatisk onlinetesttjänst för att få en grundlig kontroll av filinnehållet") and referenced in spec chapter 3.1.
- It is a **web application** ("SIE Testapplikation", JS single-page app): you upload a file in the browser and get a report. There is no public API and the exact check list is not published in the spec. Requires manual upload (no URL/curl API documented).
- Official test/sample files: the only official sample is `SIE4-Exempelfil-Sample-file-1.zip` (see Sources). No larger official test corpus is published.
- "Godkända program" approval is only available to SIE-Gruppen **member vendors** (ch. 3.2); non-members can still implement and use the format freely, and use the test service.

---

## 10. Common pitfalls (spec violations + documented importer rejections)

### Spec violations that break strict validation

1. **Wrong encoding** — UTF-8/ISO-8859-1 bytes instead of CP437 (5.8).
2. **Quoted `#SIETYP`/`#FLAGGA`/`#ORGNR`/`#FORMAT` values** — Fortnox specifically fails with "Fail to format date" on these (vendor doc); quotes are only needed for fields containing spaces.
3. **Unbalanced vouchers** — sum of `#TRANS` amounts ≠ 0 (spec #TRANS p.4).
4. **Credit sign flipped** — credit must be negative everywhere.
5. **Vouchers out of order** — not ascending per series (#VER p.7).
6. **Non-numeric account numbers** (#KONTO p.2).
7. **Missing mandatory records for 4E** — notably `#UB 0`, `#RAR`, `#KONTO` for every used account, and `#FORMAT PC8`.
8. **`#KTYP`/`#ENHET` before the corresponding `#KONTO`**.
9. **`#OMFATTN`/`#BKOD` in a 4I file, or saldo records (`#IB`/`#UB`/`#RES`…) in a 4I file** (forbidden by the table).
10. **`#RTRANS` without its identical `#TRANS` twin on the next line** — breaks pre-2008 readers and the RTRANS contract.
11. **Empty middle fields** — a field with no value that sits *before* a populated field must be written as `""` (ch. 12); trailing empty fields may be omitted. E.g. `#VER "" "" 20250101 "Porto"`.
12. **Braces not alone on their own lines**.
13. **Thousands separators / comma decimals / plus signs in amounts**.
14. **Trailing whitespace-sensitive `#GEN 20230822 `** — legal per ch. 12 but some importers are picky; write `#GEN 20250101` with no trailing spaces if sign is omitted. (Official sample writes a trailing space — so do not reject it in a reader.)
15. `#FLAGGA 1` in an exported file is common in the wild (official sample!) — do not reject; only treat 0→1 as the import acknowledgement.

### Fortnox (documented, from the official support pages cited above)

- Imports SIE types 1–4; SIE4 is "den vanligaste typen". Import **aborts at the first error** — fix one, retry, repeat.
- Errors documented: invalid/illegal characters; quoted `#SIETYP`/`#FLAGGA`/`#ORGNR`/`#FORMAT` ("Fail to format date"); **vertext/transtext longer than 50 characters** is rejected ("Lång benämning på XX verifikat" — max 50 chars); voucher on an account where a **cost center is mandatory** in Fortnox but missing in the `#TRANS` object list; **project object must have status "Pågår" (ongoing) and a start date** in Fortnox.
- Budget import sign convention (§7).
- VAT codes are not carried in SIE; Fortnox offers manual mapping at import.

### Visma (medium confidence; no current public import-error list found)

- The official SIE4 sample file is itself a **Visma Administration 2000** export — a good template for what Visma tolerates (unquoted single-word texts, `{}` object lists, CRLF, CP437, no `#KSUMMA`).
- Visma.net has its own SIE import (training doc, 2017): import into a ledger "Arbetsbok", mapping accounts/dimensions before posting; Visma eEkonomi accepts SIE4/SI files similarly. Practical Visma strictness observed in the wild (not primary-documented): duplicate `vernr` within a series, missing `#RAR`, and dates outside the fiscal year cause rejections. Treat these as **medium confidence**; validate against the spec rules above and the sietest service.

---

## 11. `#KSUMMA` (optional CRC-32 checksum)

- Optional. Two rows: a bare `#KSUMMA` after `#FLAGGA` signals checksumming, and a final `#KSUMMA <value>` at the end of the file carries the result.
- If an importer sees the opening marker but no closing value, it **should refuse the file** (truncated).
- Algorithm = standard **CRC-32**: polynomial `0xEDB88320`, initial value `0xFFFFFFFF` (preconditioning), final XOR `0xFFFFFFFF` (postconditioning) — identical to zlib's `crc32`.
- Checksum input: for every record between the two `#KSUMMA` rows, the **record label plus field contents**, in CP437 byte values, **excluding** whitespace/tabs between fields, the quotes that delimit fields, and the braces around object lists/conteringsrader; an escaped quote contributes only the quote character (not the backslash).
- For an exporter: emitting no `#KSUMMA` at all is fully compliant.

## 12. Positional fields rule (ch. 12)

All fields are positional. A missing value in a field that precedes a populated field must be written as `""` (two quote chars). Fields after the last populated value on the row need not be written at all.

```sie
#VER "" "" 20251216 "Porto"     ; serie & vernr empty (quoted), regdatum/sign omitted
```

## Appendix A — minimal valid SIE4 export (4E)

```sie
#FLAGGA 0
#FORMAT PC8
#SIETYP 4
#PROGRAM "Synthetic SME Generator" 1.0
#GEN 20250110
#FNAMN "Testbolaget AB"
#ORGNR 556123-4567
#RAR 0 20240101 20241231
#RAR -1 20230101 20231231
#KONTO 1910 Bank
#KONTO 1930 "Företagskonto"      ; CP437: "Företagskonto" with ö=0x94
#KONTO 3011 Försäljning
#KONTO 4010 Varuinköp
#KONTO 2641 Ingående moms
#KTYP 1910 T
#KTYP 3011 I
#KTYP 4010 K
#KTYP 2641 S
#IB 0 1910 50000.00
#UB -1 1910 50000.00
#UB 0 1910 37500.00
#RES 0 3011 -125000.00
#RES 0 4010 100000.00
#RES 0 2641 -12500.00
#RES -1 3011 -95000.00
#RES -1 4010 76000.00
#RES -1 2641 -9500.00
#VER A 1 20240115 "Första fakturan" 20240115
{
#TRANS 1930 {} 12500.00
#TRANS 3011 {} -12500.00
}
#VER A 2 20240116 "Inköp"
{
#TRANS 4010 {} 5000.00
#TRANS 2641 {} 1250.00
#TRANS 1930 {} -6250.00
}
```

## Appendix B — minimal valid SIE4 import (4I)

```sie
#FLAGGA 0
#FORMAT PC8
#SIETYP 4
#PROGRAM "Payroll Generator" 1.0
#GEN 20250110
#FNAMN "Testbolaget AB"
#RAR 0 20240101 20241231
#KONTO 7010 Löner
#KONTO 2710 Personalskatt
#KONTO 1930 "Företagskonto"
#VER "" "" 20240125 "Januarilön"
{
#TRANS 7010 {} 32000.00
#TRANS 2710 {} -9600.00
#TRANS 1930 {} -22400.00
}
```

## Appendix C — quick reference of all tag formats (ch. 12 table)

```
#ADRESS kontakt utdelningsadr postadr tel
#BKOD SNI-kod
#DIM dimensionsnr namn
#ENHET kontonr enhet
#FLAGGA x
#FNAMN företagsnamn
#FNR företagsid
#FORMAT PC8
#FTYP företagstyp
#GEN datum sign
#IB årsnr konto saldo kvantitet
#KONTO kontonr kontonamn
#KPTYP kontoplanstyp
#KTYP kontonr kontotyp
#OBJEKT dimensionsnr objektnr objektnamn
#OIB årsnr konto {dimensionsnr objektnr} saldo kvantitet
#OMFATTN datum
#ORGNR orgnr förvnr verknr
#OUB årsnr konto {dimensionsnr objektnr} saldo kvantitet
#PBUDGET årsnr period konto {dimensionsnr objektnr} saldo kvantitet
#PROGRAM programnamn version
#PROSA text
#PSALDO årsnr period konto {dimensionsnr objektnr} saldo kvantitet
#RAR årsnr start slut
#RES årsnr konto saldo kvantitet
#SIETYP typnr
#SRU konto SRU-kod
#TAXAR år
#TRANS kontonr {objektlista} belopp transdat transtext kvantitet sign
#RTRANS kontonr {objektlista} belopp transdat transtext kvantitet sign
#BTRANS kontonr {objektlista} belopp transdat transtext kvantitet sign
#UB årsnr konto saldo kvantitet
#UNDERDIM dimensionsnr namn superdimension
#VALUTA valutakod
#VER serie vernr verdatum vertext regdatum sign
#KSUMMA (inledande) / #KSUMMA <CRC-32>
```

(There is no `#DIM`-number-in-file vs `#SIETYP` ambiguity to handle: the type number 4 is what both 4I and 4E use; 4I vs 4E is only a convention about which records are mandatory/forbidden.)

## Surprising / non-obvious findings (for the benchmark)

1. The current official spec is document revision **4C, dated 2025-08-06** (first revision since 4B 2008-09-30) and **still mandates CP437 as the only allowed encoding**, and still calls itself "DRAFT" in PDF metadata.
2. There is an **official English translation of 4C** (the old English 4B link is superseded).
3. `#RTRANS` requires the immediately-following identical `#TRANS` row; readers that handle `#RTRANS` must ignore that twin. A row added then deleted is exported as `#BTRANS` only (4C clarification).
4. For 4I import files, `#BKOD` and `#OMFATTN` are **forbidden**, and all saldo records (`#IB`/`#UB`/`#RES`/`#OIB`/`#OUB`/`#PSALDO`/`#PBUDGET`) are forbidden; `#RAR` is only optional in 4I.
5. `#SRU` is mandatory only for types 1–2, optional in type 4.
6. Vouchers must be in ascending number order within a series — an easy-to-miss ordering constraint.
7. Fortnox documents concrete limits beyond the spec: vertext/transtext max 50 chars, unquoted `#SIETYP`/`#FLAGGA`/`#ORGNR`/`#FORMAT`, project must be "ongoing", and import aborts at the first error.
8. The official sample file ships with `#FLAGGA 1` (violating the writer-sets-0 rule in practice) — a validator should not reject that.
9. The official sample is mostly CP437 but contains one latin-1-style 0xF6 byte (ö) in `#FNR` — real-world files are messy; strict spec validation and lenient decoding are both needed.
