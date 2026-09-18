---
type: guide
title: Använda expertgranskning
description: Skapa och öppna expertgranskningar — spara utkast, kör panelen och läs resultatet.
tags: [rapporter]
---

# Använda expertgranskning

**Expertgranskning** är en egen yta i vänstermenyn. Administratör ser den alltid. Andra konton ser den när kunden har modulen påslagen under **Verktyg** → **Kunder**.

## Lista

1. Öppna **Expertgranskning** i vänstermenyn. Du ser en lista över dina granskningar (sök och filtrera på status).
2. Klicka **Ny expertgranskning** för att skapa ett utkast, eller öppna en befintlig:
   - **Utkast** → **Fortsätt konfigurera**
   - Påbörjad eller klar → **Öppna resultat** (eller **Konfiguration** om du vill ändra och köra om)
3. **Ta bort** tar bort granskningen från listan. Eventuell rapport ligger kvar under **Rapporter**.

## Konfiguration

1. Öppna fliken **Konfiguration** (via **Ny** eller en sparad körning).
2. Lägg in texten som ska granskas på ett av två sätt:
   - **Välj underlag** och ladda upp eller återanvänd en egen fil (txt, md, PDF eller Word), inklusive rättsunderlag som du har tagit fram i **Rättsunderlag**, eller öppna **rapporter** under bolagets övriga moduler. Du kan förhandsgranska PDF och rapporter, dra filer mellan mappar och ta bort en fil med **Ta bort** på raden. Word konverteras till PDF. Texten läses i bakgrunden redan vid uppladdning och en neutral dokumentöversikt skapas bredvid PDF:en. Du kan i stället klistra in text direkt.
   - Klistra in text direkt i dokumentfältet. Titel är valfritt.
3. Fyll i **Granskningsavsikt** om du vill styra vad experterna ska fokusera på. Till exempel att Devbrains är motpart i avtalet. Fältet är valfritt — lämna det tomt om dokumentet räcker.
4. Välj en **expertpanel**. Finns ingen panel skapar du en under **Expertpaneler**.
5. **Spara utkast** om du vill fortsätta senare, eller **Kör expertgranskning** när text och panel är klara.
6. Har du redan en rapport och kör om, bekräfta först — den nya körningen ersätter live-resultatet.

## Resultat

1. Fliken **Resultat** öppnas automatiskt när en körning inte längre är utkast.
2. Körningen samlar först det externa underlag som behövs och fryser det innan panelen startar. Medan det pågår visas **Research pågår** och hur många frågor som är besvarade, undersöks eller väntar. Välj **Följ researchen** för att se varje generell fråga, ansvarig expert, beroenden, källor, bedömningar och nytillkomna följdfrågor. Du kan lämna sidan och komma tillbaka; historiken sparas och vyn återansluter automatiskt. En fråga som inte kan besvaras markeras som en kunskapslucka utan att stoppa övriga frågor. När möjliga frågor är färdiga återupptas expertgranskningen automatiskt med den evidens som kunde frysas.
3. Därefter visar **Live-panel** moderator och experter. Panelen får bara använda det frysta underlaget och startar inga egna sökningar. Bara experter med relevant kompetens räcker upp handen. Noll händer är ett giltigt svar. Saknas relevant kompetens stoppas den sakliga diskussionen och frågan lämnas obesvarad. Moderatorn ställer en fråga i taget — nästa delfråga syns först när den har ställts, och hålls inte igång med analogier. Experternas turer visas formaterade (listor, fetstil, länkar) om de skriver markdown.
4. När panelen är klar öppnas **Rapport**. Där finns flikarna **Rapport** och **PDF** om underlaget var en PDF (eller Word som konverterats). Originaltexten ingår inte i HTML-rapporten. Därifrån kan du prata med **Spinndoktor**.

Underlag du laddar upp är personliga — andra på samma kund ser inte dina filer eller mappar.

Researchsteget gäller Expertgranskning i webbläsaren. Word-tillägget startar ingen research.

## Relaterade guider

- [Hantera kundmoduler](hantera-kundmoduler.md)
- [Förstå och annotera underlag](forsta-och-annotera-underlag.md)
- [Använda expertgranskning i bolagsytan](anvanda-expertgranskning-i-bolagsytan.md)
- [Granska ett dokument i Word](granska-dokument-i-word.md)
- [Hantera expertpaneler](hantera-expertpaneler.md)
- [Spinndoktor — rapportchatt](spinndoktor-rapportchatt.md)
- [Hantera rapporter](hantera-rapporter.md)
