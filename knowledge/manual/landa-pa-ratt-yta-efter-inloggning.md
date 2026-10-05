---
type: guide
title: Landa på rätt yta efter inloggning
description: Så avgör produkt och moduler var du hamnar när du loggat in — admin, bolag, SME eller en enskild modul.
tags: [grunddata]
---

# Landa på rätt yta efter inloggning

Efter magic link-inloggningen styrs din **startyta** av kundens **produkt** och **moduler**, inte bara av din roll. Samma konto kan byta yta i vänstermenyn när flera moduler är påslagna.

## Standardprodukt (adminytan)

När kunden har produkten **Standard** gäller modulerna:

1. **Politik** (personas, populationer, budskap, körningar) → du landar på **startsidan** (`/`).
2. Finns **inte** politik men **Due Diligence** → du landar i **bolagsytan** (`/bolag`).
3. Finns bara **Expertgranskning** → du landar på expertgranskningslistan.
4. Finns bara **Rättsunderlag** → du landar på rättsunderlagslistan.
5. **Inga moduler** → inloggningen meddelar att kontot saknar tilldelade moduler.

Prioritet vid flera moduler: politik före Due Diligence; därefter övriga moduler enligt samma lista.

## SME-produkt

Har kunden produkten **SME** ersätter **SME-chatten** den vanliga adminmenyn. Du landar direkt i chatten med experter och konversationer. Moduler kan fortfarande vara påslagna i bakgrunden men visas inte som separata modulmenyer.

Administratörer öppnar **Verktyg** via **Admin** i användarmenyn (modal ovanpå chatten). Se [Använda SME-chatten](anvanda-sme-chatten.md) och [Hantera kundprodukt och moduler](hantera-kundmoduler.md).

## Roller (kort)

- **Administratör** ser **Verktyg** och **Användare**; ser **Expertgranskning** och **Rättsunderlag** i menyn även om de inte är ikryssade för kunden.
- **Användare** följer kundens moduler; ingen **Verktyg**-länk.
- **Bolag** arbetar i Due Diligence-ytan när modulen finns. Se [Använda Due Diligence-ytan](anvanda-due-diligence-ytan.md).

## Byta yta efteråt

Med flera moduler byter du via vänstermenyn — till exempel mellan **Körningar**, **Kampanjer**, **Expertgranskning** och **Rättsunderlag**. Rapporter, återkoppling och bakgrundsjobb är gemensamma länkar som filtreras efter modul där det behövs.

## Relaterade guider

- [Logga in](logga-in.md)
- [Översikt av ytorna](oversikt.md)
- [Hantera kundprodukt och moduler](hantera-kundmoduler.md)
