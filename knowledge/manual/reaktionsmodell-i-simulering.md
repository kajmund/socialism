---
type: guide
title: Reaktionsmodell i simuleringen
description: Så avgörs vem som reagerar i varje rond, vem som får kommentera och när en ny chans ges vid nästa budskag.
tags: [korningar, populationer]
---

# Reaktionsmodell i simuleringen

I en OASIS-simulering reagerar **inte hela populationen samtidigt** varje reaktionsrond. Istället väljer modellen en **representativ delmängd** av populationen och följer regler för **passivt skrollande** respektive **engagemang** kring varje budskag.

Reglerna gäller **per budskag** — det vill säga per nytt inlägg som injiceras en dag (partipost, nyhetspost eller reklampost). De nollställs när **nästa budskag** injiceras.

## Stratifierat urval per rond

Vid varje **reaktionsrond** inom en dag plockas en delmängd av populationen ut. Urvalet är **stratifierat** så att distrikt, lutning och liknande spridning bevaras — inte en ren slump som råkar utesluta hela områden.

- Agenter som **inte plockas** den ronden är **inte online** just då. De får inget simulerat steg den ronden.
- Agenter som **plockas** får välja en social åtgärd utifrån vad de ser i flödet (gilla, ogilla, kommentera, göra inget, m.m.).

Första ronden efter ett nytt budskag brukar ha **något större urval** så att budskapet syns brett i populationen. Senare ronder kan vara **glesare** för att spegla att färre personer är aktiva samtidigt.

## Passiv — skrollat förbi

En agent räknas som **passiv** på ett budskag om hen var med i urvalet men bara **skrollade förbi** utan att engagera sig i tråden:

- **Göra inget**
- **Uppdatera flödet** (scrolla vidare)

Passiva agenter ** ingår inte i senare reaktionsronder på samma budskag**. De får en ny chans först när **nästa budskag eller nyhet** injiceras (ny dag med injektion, eller ny injektion samma dag).

## Engagerad — får vara med

En agent räknas som **engagerad** på budskaget om hen gjorde minst en av följande i tråden kring **samma inlägg**:

- **Gilla** eller **ogilla** själva budskagsinlägget
- **Gilla** eller **ogilla** en **kommentar** under samma inlägg
- **Skriva en kommentar** på tråden

Engagerade agenter kan **plockas igen** i senare ronder på samma budskag (fortfarande via stratifierat urval).

Reaktioner på kommentarer i **andra** trådar räknas inte — bara tråden kring det aktuella budskaget.

## Kommentera kräver samma engagemang

Regeln för **vem som får skriva kommentar** är **samma** som för att räknas som engagerad:

- Du måste ha **gillat eller ogillat** budskagsinlägget **eller** en kommentar i tråden (eller redan ha kommenterat tidigare) innan du får skriva en ny kommentar.
- **Passiva** agenter kan **inte** kommentera på samma budskag — de är uteslutna från senare ronder tills nästa budskag.

Det innebär att kommentarer i resultatet oftast kommer från personer som **faktiskt stannade till** i tråden, inte från alla som råkade se inlägget i flödet.

## När reglerna nollställs

| Händelse | Effekt |
| -------- | ------ |
| **Ny injektion** (nytt budskag/nyhet) | Alla agenter får ny chans; passiv-status försvinner för det nya inlägget |
| **Tyst dag** (ingen ny injektion) | Populationen reagerar fortfarande i ronder, men **utan nytt budskag** — passiv-status från **föregående** budskag gäller tills ett nytt injiceras |
| **Ny reaktionsrond** | Nytt stratifierat urval; passiva utesluts på **samma** budskag |

## Vad du kan förvänta dig i resultat

- **Färre kommentarer** än om hela populationen kommenterade varje rond — det är avsiktligt.
- **Mer spridd reaktion** över distrikt och lutning tack vare stratifierat urval.
- **Tydligare trådar**: kommentarer hänger oftare ihop med tidigare gilla/ogilla på samma inlägg eller kommentar.
- Vid **demo** med större population (t.ex. omkring 50 personas) ger modellen en mer trovärdig folkmassa utan att varje person agerar varje minut.

## Relaterade guider

- [Konfigurera en dag i tidslinjen](konfigurera-dag-i-tidslinjen.md) — injektioner och antal reaktionsronder
- [Starta en simulering](starta-simulering.md) — köra simuleringen
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md) — flöde, kommentarer och mätningar
- [Bygga en population](bygga-population.md) — storlek och sammansättning
