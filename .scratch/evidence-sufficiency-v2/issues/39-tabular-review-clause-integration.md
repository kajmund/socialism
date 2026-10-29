# 39 – Omerbeta Tabular Review mot clause_ssr

Type: task
Status: resolved
Blocked by: –

## Question

Ta bort det andra klausulbiblioteket från PR #429 och koppla Tabular Review till
samma klausultjänst som #428:

- Clause-kolumner ska hämta kategori/anchor set via `clause_ssr`-tjänsten, inte
  via `SsrAnchorSet(kind="clause")`.
- Ta bort/avgränsa SQL-kind `clause` från den befintliga SSR-ankarlagringen.
- Behåll Tabular Reviews egna approve/reject-labels, men de får inte implicit
  skapa aktiva ankare.
- Rebase #429 på #428, lös delade frontend-/i18n-/nav-konflikter och kör om
  backend- och frontendtester.
- Mät att Tabular Review använder samma verifierade/aktiva ankare som
  research-experimentet senare ska använda.

Ingen produktionsändring av evidensmotorn.

## Nästa åtgärd

PR #428 är mergad. Rebase #429 på main, ta bort SQL `kind="clause"` och koppla
Tabular Review till `clause_ssr`-tjänsten enligt acceptanskriterierna. Därefter
ticket 38 och 27.

## Answer

**Mergad** som `0a3848e0` (PR #429). SQL-klausulvägen är borta:
`AnchorKind` är `tone|style`, inga SQL-klausulankare/frågor/FK. Tabular Review
läser aktiva Overgraph-klausulankarset via `clause_ssr`, lagrade vektorer och
medlemskap; cache-nyckeln använder medlemskapsrevision så återkallade ankare
inte ger gamla träffar.

E2E-regression: verifierat ankare → review-cell → lås/godkänn → återkalla:
låst historik bevaras, olåsta celler blir `no_hit`, och inga SQL-klausulankare
finns. Låg score är `Ingen träff`, inte “klausul saknas”; PDF-position bevaras.
CI grönt (12 kontroller).
