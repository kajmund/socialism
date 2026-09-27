---
type: guide
title: Följa research i realtid
description: Så följer du researchförloppet medan underlag samlas innan expertgranskning eller panel.
tags: [jobb, rapporter]
---

# Följa research i realtid

Innan en **expertgranskning** eller vissa panelkörningar startar kan systemet samla **research** — generella frågor som besvaras med källor och bedömningar. Du följer förloppet i en egen vy som uppdateras live och sparar historik om du lämnar sidan.

## Öppna researchvyn

1. Under **Expertgranskning** → fliken **Resultat**, välj **Följ researchen** medan research pågår.
2. Under **Bakgrundsjobb**, öppna länken **Öppna research** på jobb som **Expertresearch**, **Due Diligence-research** eller motsvarande.
3. I **SME-chatten** kan du öppna research från research-jobbmenyn och gå till full vy.

Adressen ser ut som `/research/…` — du behöver normalt inte skriva in den själv.

## Läs statusraden

Överst visas ett av tillstånden:

- **Research pågår** — frågor besvaras och evidens samlas. Expertgranskningen återupptas automatiskt när research är klar.
- **Research klar** — evidensen är fryst och kan användas i granskningen.
- **Research klar med kunskapsluckor** — det som gick att besvara används; obesvarade frågor redovisas nedan.
- **Ingen research behövdes** — experterna bedömde att befintligt underlag räckte utan nya frågor.

Indikatorn **Live** betyder att vyn är uppkopplad. Vid **Återansluter** hämtas senaste status igen. **Sparad historik** betyder att du kan lämna sidan och komma tillbaka.

## Tolka räknare och steg

När research körs ser du:

- **Besvarade**, **Besvarade med luckor**, **Ej färdigundersökta**, **Behövde inte undersökas vidare** och **Tekniskt misslyckade** — hur frågorna fördelas. En research där inget svar finns visar de obesvarade frågorna, inte noll luckor.
- En progressrad och fyra steg: **Frågor** → **Evidens** → **Bedömning** → **Expertgranskning**.

## Läs frågekorten

Under **Generella frågor** växer ett frågeträd fram. En bred fråga kan få
indragna underfrågor. Frågor som skapats för att fylla en kunskapslucka är
tydligt märkta.

Varje kort visar:

- Status. **Besvarad** betyder att frågan har ett grundat svar. **Besvarad med luckor** betyder att svaret finns men evidensen inte räcker hela vägen. **Ej färdigundersökt** betyder att frågan fortfarande behövs och saknar ett grundat svar. **Behövde inte undersökas vidare** betyder att frågan kunde besvaras utan den grenen. **Tekniskt misslyckad** är ett faktiskt fel.
- En överordnad fråga kan vara besvarad även om en underfråga är ofärdig eller inte behövde undersökas.
- Frågans aktuella grundade svar när det finns.
- Om svaret är fullständigt eller har en kvarvarande lucka.
- Hittad evidens på de yttersta frågorna, redan innan svaret är skrivet.
- För frågor med underfrågor: vilka barnsvar som svaret bygger på. Följ trädet
  nedåt för att komma till den konkreta passagen och originalkällan.
- En kort **händelselista** under frågan: analys, uppdelning, sökning, hittad evidens och svar. Etiketten på frågan följer den senaste händelsen, så den lämnar **Söker evidens** när evidens har hittats.

Längst ner finns en **teknisk händelselogg** med råa händelser — användbar om något verkar ha fastnat.

## Relaterade guider

- [Använda expertgranskning](anvanda-expertgranskning.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
- [Använda SME-chatten](anvanda-sme-chatten.md)
- [Köra en Due Diligence-kampanj](kora-dd-kampanj.md)
