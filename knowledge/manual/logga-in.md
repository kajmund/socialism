---
type: guide
title: Logga in
description: Så loggar du in i Opinionssimulator med admin-, användar- eller bolagskonto.
tags: [grunddata]
---

# Logga in

Opinionssimulator kräver inloggning. Det finns ingen registrering — du använder ett av de konton som finns i verktyget.

## Steg

1. Öppna appen i webbläsaren. Om du inte är inloggad visas inloggningssidan.
2. Fyll i **Användare** och **Lösenord** i rutan mitt på skärmen.
3. Klicka **Logga in**.
4. Du landar på den yta som kundens tilldelade moduler styr:
   - en modul → direkt till den ytan (politik på startsidan, due diligence på bolagsytan)
   - två eller fler moduler → **Välj modul**, där du öppnar den yta du vill arbeta i
   - inga moduler → inloggningen visar att kontot saknar tilldelade moduler

## Konton

| Användare | Lösenord | Roll |
| --------- | -------- | ---- |
| `admin` | `admin` | Administratör — ser allt, inklusive **Verktyg** (konfigurationer, kunder, panelkatalog, playground och cache) |
| `user` | `user` | Användare — samma dagliga ytor som politikmodulen men utan **Verktyg** och konfiguration |
| `bolag` | `bolag` | Bolag — due diligence-ytan. Får även politikytan om administratören kryssat i den för kunden |

Modulerna per kund ställs in under **Verktyg** → **Kunder**. En ny inloggning (eller omladdning) tar upp den aktuella uppsättningen.

## Roller

- **Administratör** kan öppna **Verktyg** och ändra konfigurationer, kundmoduler, SSR-ankare, playground och embedding-cache.
- **Användare** ser inte **Verktyg** i menyn. En länk till konfiguration leder tillbaka till startsidan.
- **Bolag** arbetar i due diligence-ytan. Roll styr inte längre ensam vilken yta du får in — det gör kundens tilldelade moduler.

## Logga ut

Klicka **Logga ut** uppe till höger i menyn (på liten skärm: öppna menyknappen först).

## Relaterade guider

- [Översikt av ytorna](oversikt.md)
- [Hantera kundmoduler](hantera-kundmoduler.md)
- [Byta gränssnittsspråk](byta-granssnittssprak.md)
- [Hantera konfigurationer](hantera-konfigurationer.md)
