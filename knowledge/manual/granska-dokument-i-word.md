---
type: guide
title: Granska ett dokument i Word
description: Öppna tillägget i Word, välj expertpanel och tillämpa eller avfärda förslagen i sidopanelen.
tags: [jobb, rapporter]
---

# Granska ett dokument i Word

Tillägget **Expertgranskning** sitter i Word, inte i webbläsaren. Det använder samma expertpaneler som i admin.

## Första gången

1. Öppna dokumentet i **Word på datorn** och öppna tillägget från fliken **Start** (Devbrains-huvudet, knappen **Granska**).
2. Klistra in din inloggningstoken (samma som efter inloggningslänken) och spara den. Token stannar i Word.
3. Välj en **expertpanel**. Listan visar bara panelerna för din kund.
4. Fyll i **Granskningsavsikt** om du vill styra vad experterna ska fokusera på, till exempel att Devbrains är motpart i avtalet. Fältet är valfritt.
5. Klicka **Granska**. Tillägget läser dokumentets stycken och startar en granskning.

En moderator läser först varje del av dokumentet och hoppar över rent administrativt innehåll, till exempel namn och kontaktuppgifter. Bara delar som kräver bedömning går vidare till experterna, som frågor. Varje expert får hela dokumentet som underlag och kommenterar bara de frågor där hen räcker upp handen. Förslagen visas löpande i sidopanelen och fästs vid det stycke som bär observationen först när du tillämpar dem. Kommentarerna använder dokumentets partsnamn och antar inte att du är kund eller leverantör. När flera experter gör samma observation slås den ihop till en kommentar som visar vilka som stödjer den. Om experterna faktiskt är oeniga syns båda bedömningarna. Klausulnummer (till exempel 2.1) används internt så att experten kan peka rätt — de läggs inte in i kommentaren du ser.

När minst två experter är överens om en konkret ny formulering kan tillägget också föreslå en **omskrivning**. Förslagen visas i sidopanelen. Inget skrivs i dokumentet förrän du klickar **Tillämpa**. **Avfärda** lämnar dokumentet orört.

Om dokumentet har ändrats, eller om tillägget inte kan peka ut rätt stycke säkert, blir förslaget olösligt. Då kan du bara avfärda det. Ett förslag som fastnat i **Tillämpas…** är osäkert — tillägget försöker inte igen av sig själv.

När granskningen är klar betyder det att förslagen är färdiggenererade, inte att du har beslutat om alla. Öppna sidopanelen igen så ligger samma förslag kvar, även om jobbet redan är klart.

## Granska igen

Klicka **Granska** en gång till i samma dokument först när varje förslag är tillämpat eller avfärdat. Tidigare tillämpade kommentarer i Word markeras då som lösta. Ett nytt jobb startas inte om det finns öppna eller osäkra förslag.

Om du stänger sidopanelen medan en granskning fortfarande körs, och öppnar den igen, fortsätter samma jobb. Ett nytt jobb startas inte förrän det pågående är klart.

## Relaterade guider

- [Använda expertgranskning](anvanda-expertgranskning.md)
- [Hantera expertpaneler](hantera-expertpaneler.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
