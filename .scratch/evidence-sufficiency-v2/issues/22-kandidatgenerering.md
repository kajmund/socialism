# Kandidatgenerering för lågoverlappande motsägelser

Type: grilling
Status: resolved
Blocked by: 21

## Question

Kan SWE generera relevanta faktapar även när påståendena beskriver samma
sakfråga med helt olika formuleringar?

B3b visade att `candidate_miss_synonyms` aldrig blir ett kandidatpar, och att
Jev dessutom bedömer paret fel när det väl presenteras. Ranking kan inte rädda
ett par som inte genereras.

- Utgå från kandidatgenereringens nuvarande deterministiska signaler
  (entitet, definition, delade tokens) och mät Candidate Recall före/efter.
- Pröva kompletterande signaler utan att låta generell embeddinglikhet dominera:
  SSR-liknande sakfrågeklassificering när verifierade ankare finns, annars
  deterministiska synonym-/kontextsignaler.
- Mät: Candidate Recall, antal nya kandidater, falska par, Jev-anrop per korrekt
  beslut och kostnad. Recall@Budget och slutlig beslutskvalitet mäts separat.
- Förregistrera adoptionskriterium: bättre Candidate Recall för kända
  motsägelsepar utan att falska par eller slutlig false-sufficient ökar.
- Om Jev felbedömer paret även när det genereras: dokumentera som separat
  semantiskt beslutproblem, inte som kandidatfel.

Ingen produktionsändring; A3-kontraktet och 40-parsbudgeten är oförändrade.

## Låst protokoll före körning (2026-10-23)

**Fokus:** Candidate Recall för kända motsägelsepar med låg lexikal överlappning.
Ranking, budget och Jev är oförändrade och mäts inte här.

Armar: deterministisk kandidatgenerering (A), embeddings (B), hybrid union (C).
Alla körs på samma claims; embeddings är endast kandidatgenerering, inte
rankningssignal.

**Fall:** `candidate_miss_synonyms`, två nya synonyma motsägelser (semester,
uppsägningstid), två förenliga kontroller (period, entitet) samt late_evidence
som referens.

**Mått:** Candidate Recall för kända par, antal kandidater, embeddinganrop och
kostnad. Rankingens Recall@Budget mäts separat.

**Förregistrerat beslutskriterium:** hybrid får ersätta deterministisk
generering endast om Candidate Recall för motsägelsepar är högre (minst ett
nytt lågoverlappande par) och kandidatvolymen är högst 10× den deterministiska.
Annars behålls deterministisk generering och SSR/sakfrågegruppering blir nästa
steg.

## Answer

**Körd 2026-10-23** (commit `6210b26c`) enligt det låsta protokollet. Ingen
ranking, budget eller Jev inblandad.

| Strategi | Candidate Recall (motsägelser) | Recall (förenliga) | Medel kandidater | Embeddinganrop/texts |
| --- | ---: | ---: | ---: | ---: |
| Deterministisk | 0.25 | 1.00 | 196.3 | 0 / 0 |
| Embeddings | 0.75 | 1.00 | 19.5 | 6 / 59 |
| Hybrid | **1.00** | 1.00 | 196.8 | 6 / 59 |

Den deterministiska generatorn missar alla tre syntetiska lågoverlappande
motsägelser; hybrid lyfter dem till samma kandidatvolym som deterministisk.
Embeddings ensam missar `late_evidence`, så hybrid behövs.

Förregistrerade kriterier: högre recall, minst ett nytt lågoverlappande par och
högst 10× kandidatvolym → **uppfyllda**. Beslut: `CANDIDATE_GENERATION_IMPROVED`.

**Men detta är inte ett beslutsgenombrott:** B3b visade att Jev kan bedöma dessa
par fel (candidate_miss_synonyms gav SCOPE_DIFFERENCE), och ingen Jev kördes här.
Därför ingen produktionsändring; B4b (ticket 24) kör fullt live-arm med hybrid
innan adoption. Metadata-rankningen ligger kvar som fryst jämförelsearm.

Nästa: B4b full arm, därefter SSR-sakfrågegruppering och beslutsdiagnostik.
