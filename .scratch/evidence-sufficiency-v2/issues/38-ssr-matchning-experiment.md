# 38 – SSR-klausulmatchning och D-jämförelse

Type: task
Status: open
Blocked by: 40, 43

## Question

Koppla ihop verifierade aktiva ankare med research:

- Matchning av en osedd klausul mot aktivt index ger kategori, similarity och
  abstention; inga Jev/narrativa anrop vid matchning.
- Mät SSR-klassificering: precision, recall, abstention på osedda avtal där
  testavtalen inte finns i ankarbiblioteket.
- Därefter SSR + SWE mot D: incremental Candidate Recall och Recall@5/10/20/40,
  kostnad, latens och nya false-sufficient.
- Avgränsning: om SSR inte förbättrar Candidate Recall, tidig Recall@Budget
  eller kostnad mot D, ska SSR inte in i evidensmotorn.

Först därefter kan ticket 27 köras fullt ut.
