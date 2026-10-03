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

- **Besvarade**, **Pågående**, **Väntar** och **Luckor** — hur frågorna fördelas.
- En progressrad och fyra steg: **Frågor** → **Evidens** → **Bedömning** → **Expertgranskning**.

## Läs frågekorten

Under **Generella frågor** finns ett kort per fråga med:

- Status (t.ex. besvarad, undersöks, otillräcklig evidens, obesvarad).
- Ansvarig expert och vem som ställde frågan.
- Beroenden — om frågan väntar på att en annan ska bli klar.
- Varför frågan behövs och den kontextspecifika formuleringen.
- Hittade källor och bedömning (fullständighet, stödjande evidens, luckor, motstridigheter).

En experts fråga visas tillsammans med sin bedömning och sina källor i samma kort. Stödjande evidens visas med källornas namn. Verkliga följdfrågor har egna kort.

Längst ner finns en **teknisk händelselogg** med tidsstämplade händelser — användbar om något verkar ha fastnat.

## När ett tidigare svar återanvänds

Har samma fråga redan besvarats i samma sammanhang kan researchen bli klar direkt
med det tidigare underlaget. Källorna och bedömningen visas som vanligt. Systemet
kontrollerar att underlaget fortfarande är giltigt. En närliggande fråga kan också
använda ett tidigare svar efter en kontroll av att det täcker den nya frågan.
Finns bara ett delvis användbart svar fortsätter researchen med det underlaget
som grund för att undersöka luckorna.

## Relaterade guider

- [Använda expertgranskning](anvanda-expertgranskning.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
- [Använda SME-chatten](anvanda-sme-chatten.md)
- [Köra en Due Diligence-kampanj](kora-dd-kampanj.md)
