---
type: guide
title: Spinndoktor — resonera kring en rapport
tags:
  - rapporter
---

# Spinndoktor — resonera kring en rapport

Spinndoktor är en chatt kopplad till **en enskild rapport**. Den hjälper dig tolka resultat utifrån körningens faktiska siffror — engagemang, ton, budskapsstilar och målgrupper — utan att du behöver läsa rådata eller tekniska termer.

## Öppna Spinndoktor

1. Gå till **Rapporter** och öppna en rapport som har status **Klar**.
2. I sidhuvudet: växla från **Rapport** till **Spinndoktor**.

Hjälpchatten (FAB nere till höger) är en separat funktion och kan vara öppen samtidigt.

## Arbetsyta

- **Chatt** ligger fast i en panel till vänster.
- **Rutnät** fyller resten av ytan — Spinndoktorn lägger dit kort medan ni pratar.
- **Visa rapport** (höger) öppnar samma HTML-rapport som referenspanel. Den är stängd som standard.

Du kan panorera och zooma i rutnätet och flytta kort fritt. Rutnätet töms när du lämnar Spinndoktor-vyn.

## Ställa frågor

- Skriv frågor på vanlig svenska, t.ex. *Vad säger siffrorna om mottagandet?*, *Hur landade budskapet?* eller *Vilken budskapsstil funkade bäst?*
- Spinndoktorn ser rapportens översiktssiffror direkt. När den behöver **testbudskapet**, citat från flödet, intervjusvar eller en namngiven medborgare hämtar den det själv med verktyg.
- Den kan också slå upp **SCB-statistik** och söka på **Wikipedia** eller **webben** när det hjälper tolkningen.
- Den har **inte** hela transkriptet i ett svep — den söker fram det som frågan kräver.
- Chatthistoriken sparas **per rapport**. En annan rapport har en egen historik.

## Widgets på rutnätet

Spinndoktorn kan lägga till tre typer av kort:

1. **Graf** — stapel, ring eller enskild siffra utifrån rapportdata eller beräkningar.
2. **Anteckning** — kort sammanfattning av ett fynd.
3. **Rapportklipp** — avsnitt ur HTML-rapporten (samma avsnitt som när den pekar dig till `[[ref:…]]`).

Varje kort visar en liten tidsstämpel — hur lång tid som gick från din fråga till att kortet dök upp (för utvärdering av känsla och svarstid).

När Spinndoktorn pekar dig till ett avsnitt i rapporten kan du öppna referenspanelen och scrolla dit, eller öppna klippet från kortet.

## Rensa chatt

**Rensa chatt** tar bort historiken för den här rapporten. Det påverkar inte själva rapporten och tömmer inte rutnätet förrän du byter vy eller laddar om sidan.

## Begränsningar (prototyp)

- Rutnätet fylls bara av Spinndoktorn — du kan inte lägga till kort manuellt.
- Kort sparas inte mellan sessioner.
- Inga verktyg för att köra om SSR, intervjua agenter eller skapa egna diagram utanför chatten.
