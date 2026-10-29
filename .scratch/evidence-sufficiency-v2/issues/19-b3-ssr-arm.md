# B3-D – SSR-ankare som prioriteringssignal

Type: grilling
Status: open
Blocked by: 27

## Question

Tillför verifierade SSR-ankare något utöver B3-B/C när SWE väljer vilka
faktapar Jev ska jämföra?

- Kör endast när det finns tillräckligt många mänskligt verifierade SSR-ankare;
  bygg inte in en o verifierad ankarbibliotek i B3.
- SSR ska kunna användas på **båda** ställena: kandidatgenerering (gruppera
  påståenden efter sakfråga även vid låg inbördes likhet) och ranking. SSR är en
  signal, inte ett beslut; den får inte avgöra att en motsägelse finns.
- Mät först Candidate Recall, därefter Recall@40; SSR ska inte införas som
  generell embedding-ranking.
- Prioritetsfeatures: semantisk likhet mellan påstående och ankare, gemensam
  kategori/entitet, extraherade värde-/polaritetsskillnader, källoberoende,
  redan prövad relation.
- Jämför mot B3-A/B/C på samma fall och Recall@Budget-kurva; mät
  embedding-/ankarkostnad separat.
- Beslutskriterium: bättre Recall@Budget eller färre Jev-anrop för samma recall,
  utan ökade false-sufficient. Annars behåll B3-B/C.

## Reference

B4c-arm D (hybrid kandidatgenerering + metadata-prioritering) är referens:
22/26 rätt, 0 false-sufficient, Candidate Recall 14/14, Recall@40 14/14.
SSR ska jämföras mot D, inte mot en äldre baseline. Mät två effekter separat:
(1) SSR som hittar nya kandidatpar, (2) SSR som förbättrar ordningen bland redan
hittade par. SSR får inte avgöra konflikter.

## Precondition

Körs först när verifierade SSR-ankare finns i tillräcklig mängd. Återanvänder
B3:s prioritetsgränssnitt; SSR är en ordering, aldrig ett motsägelsebeslut.
