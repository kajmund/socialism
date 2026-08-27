---
type: guide
title: Spinndoktor — resonera kring en rapport
tags:
  - rapporter
---

# Spinndoktor — resonera kring en rapport

Spinndoktor är en chatt kopplad till **en enskild rapport**. Den hjälper dig tolka resultat utifrån körningens faktiska siffror — engagemang, ton, budskapsstilar och målgrupper — utan att du behöver läsa rådata eller tekniska termer.

## Öppna Spinndoktor

1. Gå till **Rapporter** och öppna en rapport som har status **Klar** — du kommer direkt till Spinndoktor.
2. Tillbaka till rapporten: klicka på **Rapport** uppe i chattrutan. Därifrån tar **Spinndoktor** dig tillbaka.

Hjälpchatten (FAB nere till höger) är en separat funktion och kan vara öppen samtidigt.

## Arbetsyta

- **Rutnätet** fyller hela sidan. Rapportens sidhuvud (titel, status, ta bort) syns inte här — bara chatten, rutnätet och ev. rapportpanel. Du kan panorera och zooma under panelerna och flytta kort fritt.
- **Chatten** ligger flytande till vänster ovanpå rutnätet. **Visa chatt**, **Rensa rutnät** och **Visa rapportpanel** ligger som en flytande rad i mitten av rutnätet.
- **Visa rapportpanel** öppnar samma HTML-rapport som en flytande panel till höger. Den är stängd som standard. **Full bredd** låter panelen fylla ut den lediga ytan; **Normal bredd** tar tillbaka den smala panelen.

Rutnätet töms när du lämnar Spinndoktor-vyn.

## Ställa frågor

- Skriv frågor på vanlig svenska, t.ex. *Vad säger siffrorna om mottagandet?*, *Hur landade budskapet?* eller *Vilken budskapsstil funkade bäst?*
- Spinndoktorn ser rapportens översiktssiffror direkt. Hen hämtar själv **testbudskapet**, citat från flödet, intervjusvar och namngivna medborgare med verktyg — utan att fråga dig först.
- Hen kan också slå upp **SCB-statistik** och söka på **Wikipedia** eller **webben**, och lägger grafer, anteckningar och intervjuer på rutnätet i samma svar.
- Hen har **inte** hela transkriptet i ett svep — hen söker fram det som gör svaret bättre.
- Chatthistoriken sparas **per rapport**. En annan rapport har en egen historik.

## Widgets på rutnätet

Spinndoktorn kan lägga till fyra typer av kort:

1. **Graf** — stapel, ring eller enskild siffra utifrån rapportdata eller beräkningar.
2. **Anteckning** — kort sammanfattning av ett fynd.
3. **Rapportklipp** — avsnitt ur HTML-rapporten (samma avsnitt som när den pekar dig till `[[ref:…]]`).
4. **Intervju** — chatt med en persona från körningen. Scrolla i tråden; flytta kortet i titeln.

Varje kort visar en liten tidsstämpel — hur lång tid som gick från din fråga till att kortet dök upp (för utvärdering av känsla och svarstid). Kopieringsikonen uppe till höger kopierar kortets text; krysset stänger kortet. Rutnätet sparas per rapport — kort och deras läge finns kvar när du kommer tillbaka. **Rensa rutnät** tar bort alla kort.

När Spinndoktorn pekar dig till ett avsnitt i rapporten kan du öppna referenspanelen och scrolla dit, eller öppna klippet från kortet.

## Rensa chatt

**Rensa chatt** tar bort historiken för den här rapporten. Det påverkar inte själva rapporten och tömmer inte rutnätet förrän du byter vy eller laddar om sidan.

## Begränsningar (prototyp)

- Rutnätet fylls bara av Spinndoktorn — du kan inte lägga till kort manuellt.
- Inga verktyg för att köra om SSR eller skapa egna diagram utanför chatten.
