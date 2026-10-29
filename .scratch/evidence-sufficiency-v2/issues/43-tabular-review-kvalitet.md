# 43 – Tabular Review kvalitetsmätning mot verifierat facit

Type: task
Status: open
Blocked by: 41, 42

## Question

Mät Tabular Review mot det frysta, mänskligt verifierade klausulfacit som ticket
41 tar fram på den ingästa korpusen från ticket 42.

- Recall@1/3/5 per kategori, korrekt abstention, falska träffar och missar.
- Kontrollera att negativa fall (klausulen finns inte) verkligen är negativa i
  hela dokumentet, inte bara att kandidaten saknas.
- Ankaravtal och testavtal hålls åtskilda; inga testavtal i ankarbiblioteket.
- Låg score ska vara `Ingen träff`; mät hur ofta det är korrekt abstention vs
  miss och redovisa separat.
- Ingen Jev/narrativ LLM i mätningen; ingen ändring i research/SWE.

Därefter kan ticket 38 (SSR mot D) följa.
