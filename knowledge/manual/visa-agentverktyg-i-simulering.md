---
type: guide
title: Visa agentverktyg i simulering
description: Så ser du vilka externa verktyg en agent anropade före ett inlägg eller en kommentar.
tags: [korningar]
---

# Visa agentverktyg i simulering

Om körningen har **agentverktyg** aktiverade (t.ex. webbsök eller matematik) kan agenter anropa dem innan de skriver. I resultatflödet kan du se exakt vilka anrop som gjordes.

## Steg

1. Öppna **Körningar** och gå till fliken **Resultat** på en klar körning.
2. Expandera ett försök och bläddra i **Flödet**.
3. Inlägg eller kommentarer där agenten använt verktyg märks med en etikett **Verktyg använda**.
4. Klicka på **skiftnyckelikonen** bredvid inlägget eller kommentaren.
5. I rutan ser du varje verktygsanrop under samma dag (tick): vilket verktyg, vilken fråga och vilket svar som kom tillbaka.
6. Stäng rutan när du är klar.

Om inga verktyg var aktiverade i körningen, eller agenten inte anropade något, syns varken etikett eller ikon.

## Relaterade guider

- [Skapa en ny körning](skapa-korning.md) — aktivera agentverktyg
- [Inspektera nätverk i simulering](inspektera-natverk-i-simulering.md)
- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
