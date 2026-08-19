---
type: guide
title: Logga in
description: Så loggar du in i Opinionssimulator med admin- eller användarroll.
tags: [grunddata]
---

# Logga in

Opinionssimulator kräver inloggning. Det finns ingen registrering — du använder ett av de två konton som finns i verktyget.

## Steg

1. Öppna appen i webbläsaren. Om du inte är inloggad visas inloggningssidan.
2. Fyll i **Användare** och **Lösenord** i rutan mitt på skärmen.
3. Klicka **Logga in**.
4. Du landar på startsidan. Menyn visar de ytor du har tillgång till.

## Konton

| Användare | Lösenord | Roll |
| --------- | -------- | ---- |
| `admin` | `admin` | Administratör — ser allt, inklusive **Verktyg** (konfigurationer, playground och cache) |
| `user` | `user` | Användare — samma dagliga ytor men utan **Verktyg** och konfiguration |

## Roller

- **Administratör** kan öppna **Verktyg** och ändra konfigurationer, SSR-ankare, playground och embedding-cache.
- **Användare** ser inte **Verktyg** i menyn. En länk till konfiguration leder tillbaka till startsidan.

## Logga ut

Klicka **Logga ut** uppe till höger i menyn (på liten skärm: öppna menyknappen först).

## Relaterade guider

- [Översikt av ytorna](oversikt.md)
- [Byta gränssnittsspråk](byta-granssnittssprak.md)
- [Hantera konfigurationer](hantera-konfigurationer.md)
