---
type: guide
title: Köra en Due Diligence-kampanj
description: Skapa en kampanj, chatta fram bolag, köra research, konfigurera körningar och öppna resultat.
tags: [jobb, rapporter]
---

# Köra en Due Diligence-kampanj

En **Due Diligence-kampanj** samlar en sökbrief, kandidatbolag och körningar. Du chattar fram bolag i en modal och väljer vilka som ska ligga i kampanjen. Varje kandidat har en egen körning, likadant som i politikmodulen: resultat, konfiguration och ta bort.

## Skapa kampanjen

1. Öppna **Kampanjer** i menyn.
2. Välj **Starta ny Due Diligence-kampanj**.
3. Ange ett namn och skapa kampanjen.

## Sök och välj bolag

1. På **Kandidater**, välj **Sök bolag**.
2. Beskriv vilka bolag du söker, till exempel bransch, ort eller storlek. Du kan också välja ett färdigt förslag.
3. Assistenten söker och visar träffar.
4. Markera bolagen du vill ha. **Avmarkera alla** tar bort markeringen; du kan också avmarkera enskilda träffar.
5. Välj **Lägg till i kampanjen**.

Bolag som redan finns i kampanjen syns i resultatet men kan inte väljas igen.

Din första beskrivning sparas som kampanjens sökbrief.

## Vad som syns i kampanjen

Kampanjen är uppdelad i flikar:

- **Översikt** — kampanjens namn.
- **Kandidater** — bolagen du lagt till.
- **Körningar** — en körning per kandidat. Öppna resultat, gå till konfiguration eller ta bort körningen.

När minst ett bolag är tillagt låses sökbriefen. Du kan chatta vidare och lägga till fler bolag.

På kandidatlistan syns namn, organisationsnummer, omsättning och anställda. Fäll ut ett bolag för att se resten: **årsredovisningar** (ladda upp PDF eller bild, ladda ner eller ta bort), F-skatt, moms, styrelse, koncern, varumärken, SNI, händelser och räkenskaper. Nyckeltalen visas som staplar per år, likadant som i Due Diligence-rapporten. Exakta belopp och övriga poster står i tabeller under diagrammen.

## Konfigurera och starta en körning

1. Öppna fliken **Körningar**. Där syns en körning per kandidat — sök, filtrera och växla mellan rutnät och lista.
2. Välj **Fortsätt konfigurera** på kandidaten (eller **Konfiguration** om körningen redan har startats).
3. Under **Konfiguration** väljer du expertpanel. Research-läget syns som en sammanfattning; kartläggningen görs under **Research**.
4. Öppna **Research** → **Koncern** och välj **Kartlägg koncern**. Jobbet listar upp till 25 bolag i koncernen — även syskon och deras dotterbolag, till exempel Academic Work i Akind-koncernen. Trädet hämtas från Allabolags koncernuppgifter; nyckeltal slås upp per bolag. I vyn syns en sammanfattning (bolag, omsättning, anställda, resultat), en sökbar lista i strukturordning och detaljer för det valda bolaget till höger (styrelse och understruktur). Finns fler bolag kvar väljer du **Kartlägg fler**. Personerna i styrelserna samlas som en sidoeffekt. Relaterade bolag utanför koncernen tas inte med. Saknade uppgifter hamnar under **Inte hittat**; om Allabolag inte svarar stannar jobbet.
5. Öppna **Research** → **Personer**. Sök eller filtrera listan, markera en eller flera personer och välj **Utred valda**, eller **Utred alla**. Välj en person i listan för att se dossiern till höger: uppdrag i koncernen, uppdrag utanför och sociala träffar. Revisorer får en not om att den långa listan beror på revisorsrollen. När personerna redan är utredda (eller när du vill kartlägga koncernen om) måste du först välja **Rensa research**.
6. Tillbaka under **Konfiguration**, välj **Kör Due Diligence-panel**.

När research är klar syns koncern och personer under fliken **Research**. När du kör panelen öppnas **Resultat** med **Live-panel** — utfrågningen spelas upp där, även om du kör om. **Rapport** fylls i när den nya rapporten är klar; den gamla rapporten tas bort från körningen (den ligger kvar under Rapporter). Knappen **Spinndoktor** syns på rapportfliken och öppnar rapporten i fullbredd. Panelen får dossiern i underlaget om research körts först. Från resultat kan du gå tillbaka till **Konfiguration**.

I Due Diligence-rapporten jämförs räkenskaperna med staplar per år — omsättning, resultat, EBITDA och övriga nyckeltal — i stället för en år-för-år-lista. Exakta belopp står i tabellen under diagrammen.

I live-panelen leder Spinndoktor bara — experterna talar själva när de räcker upp handen. Nästa delfråga syns först när Spinndoktor har ställt den. Deras turer visas formaterade om de skriver markdown. Varje expert bedömer bara de delfrågor som är hens kärnkompetens, och säger varför frågan är (eller inte är) hens. När de poängsätter skriver de också varför, med fakta från underlaget — inte bara siffran. Finns nyckeltal i grunddata märks poängen **Grunddata**, även på andra delfrågor än finansiell hälsa. Om ingen räcker upp handen hoppas poängen över, och rapporten förklarar luckan under **Obesvarade delfrågor**. Relaterade bolag från Allabolag visas inte i underlag eller rapport.

Experterna i panelen, expertchatten (intervju och in-character) och Spinndoktor kan slå upp bolagsuppgifter när ett nyckeltal saknas. Siffror som redan finns i grunddata söks inte om. Experterna kan också söka på webben och Wikipedia efter annat än de redan givna nyckeltalen.

## Ta bort en körning

1. Öppna fliken **Körningar**.
2. Välj **Ta bort** på körningen.
3. Bekräfta med **Ta bort?**.

Kandidaten ligger kvar i kampanjen. Rapporten som redan skapats finns kvar under **Rapporter**.

## Ta bort en kampanj

1. Öppna **Kampanjer**.
2. Välj **Ta bort** på kampanjen.
3. Bekräfta med **Ta bort?**.

Tidigare rapporter från kampanjen finns kvar under **Rapporter**.

## Relaterade guider

- [Hantera kampanjer](hantera-kampanjer.md)
- [Komponera en expertpanel](komponera-expertpanel.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
- [Hantera rapporter](hantera-rapporter.md)
