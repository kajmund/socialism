---
type: guide
title: Använda SME-chatten
description: Arbeta med experter i text och live voice, granska källor och skapa dokument i samma arbetsyta.
tags: [personas, populationer, grunddata]
---

# Använda SME-chatten

När din kund har produkten **SME** öppnas chatten direkt efter inloggning. Den vanliga adminmenyn ersätts av en lista med experter och konversationer.

## Välj konversation

- **Alla** visar både enskilda experter och expertpaneler.
- **Olästa** visar experter och expertpaneler som har nya svar.
- **Grupper** visar bara expertpaneler.
- Förstoringsglaset i vänsterkolumnen öppnar chattlistan med sökning och filter. Sökfältet filtrerar den lista som är öppen.

En gul markering visar antalet olästa expertsvar. När du öppnar konversationen markeras de som lästa. Förhandsvisning, tid och lässtatus för enskilda experter gäller den privata chatt du har valt.

I den smala expertlistan öppnar sökikonen en dialog med sökfält, filter och förhandsvisningar. Dialogen visar vilket workspace konversationerna hör till.

## Chatta med en expert

Välj först företagets eller kundens arbetsyta och därefter en privat chatt och expert. Administratörer väljer även kund. Skriv i fältet **Aa** och skicka. Text och röst använder samma expert och samma arbetsyta. Chattens svar sparas tillsammans med arbetsytan.

Papperskorgsknappen i chatthuvudet är **Rensa chatt**. Den tar bort meddelandena i den öppna chatten. Samma text försvinner även i expertens andra arbetsytor. Röstmeddelanden där ligger kvar. Minnen, dokument och företagets expertintervju ändras inte.

När du byter expert eller privat chatt avslutas det aktuella samtalet. Redan sparade meddelanden ligger kvar. Dokumentjobb som har startats fortsätter även när samtalet avslutas.

Telefonknappen vid skrivfältet startar **live voice**. Tillåt mikrofonen i webbläsaren. Experten tar upp tråden från det ni senast pratade om och pratar först. Du kan stänga av mikrofonen, avbryta ett uppläst svar eller avsluta röstsamtalet. Du kan också skriva medan röstsamtalet är aktivt; texten avbryter uppläsningen
men samtalet fortsätter. Korta lyssnarsignaler som *mm* avbryter inte svaret.
Om du talar en längre stund kan experten nynna med utan att det sparas i
chatten. När ett uppslag tar tid kan experten säga att hen väntar eller att
en del har kommit. Talade frågor och expertsvar visas i chatten. Dokument och
sparade jobb ligger kvar när samtalet avslutas.

I expertens redigering väljer du röstfunktion. **Socialism Live Speech** använder
workspace-chattens vanliga modell, verktyg och historik. Där väljer du också den
ElevenLabs-röst som ska läsa upp expertens svar. Valen **Gemini** och
**ElevenLabs** behåller sina separata leverantörssamtal.

Med v4 Turbo kan uppläsningen använda skratt, suckar och andra uttryck. Dessa
röstinstruktioner hörs i framförandet men visas inte som taggar i chatten.

Om mikrofonen nekas visar chatten ett fel och du kan fortsätta skriva. Om
transkriberingen eller uppläsningen inte är tillgänglig visas ett fel i chatten;
textchatten ligger kvar.

## Arbeta med källor och presentationer

Chatten kan upptäcka dokument som redan finns i företagets och den valda kundens arbetsyta. Be exempelvis ”läs kvittot” eller ”sammanfatta avtalet”. Experten väljer det relevanta dokumentet och behöver inte be dig ladda upp det igen.

Skriv `@` i meddelandefältet för att peka ut ett underlag i arbetsytan. En lista med dokumentnamn visas. Välj ett namn, eller skriv början av det, så fylls hela namnet i efter `@`. Pil upp och ned flyttar i listan, Enter infogar namnet och Escape stänger listan.

Ladda upp nya dokument genom filväljaren i arbetsytan. Bearbetningen visas som ett bakgrundsjobb. Vänta tills dokumentet är läsbart innan du ber experten analysera det. Dokument som saknar textlager visar en kunskapslucka. Om bearbetningen avbryts visas ett fel; filen räknas inte som färdig kunskap.

Du kan fråga om en redan uppladdad, klar fil direkt i text eller röst, till exempel **Läs kvittot och ange datum och belopp**. Experten kan återanvända filer från det aktuella workspacet och företagets workspace. Du behöver inte ladda upp filen igen eller skriva ordet research. Andra klienters filer ingår inte.

Välj kunskapsområde i arbetsytans överkant: **Workspace**, **Allmän kunskap** eller **Research**. Det valda området följer med nästa fråga. Research behöver egna tillgängliga resultat; expertens minnen räknas inte som dokumentkällor.

Arbetsytans vyer visar olika delar av samma uppgift:

- **Evidens** visar källkort och stabila referensnummer.
- **Dokument** öppnar källan vid rätt sida och markerar den hänvisade texten. Två dokument kan visas bredvid varandra med egen sida och förstoring.
- **Jämförelse** visar jämförda uppgifter med källreferenser. Saknade uppgifter framgår.
- **Relationer** visar händelser, villkor och konsekvenser som en graf. Tolkningar skiljs från källbelagda samband. Klicka på en referens för att öppna stödet.

Du kan styra vyerna med rösten, till exempel ”öppna källan”, ”jämför de här uppgifterna” eller ”visa sambanden”. Experten bekräftar visningen efter att gränssnittet öppnat resultatet.

## Skapa och revidera dokument

Be experten skapa ett utkast. Utkastet bygger på det ni just pratat om och på de källor som faktiskt stöder uppdraget. Uppladdade filer som inte handlar om saken blir inte hela underlaget. Utkastet skapas som ett jobb och öppnas när det är färdigt. Du kan redigera block och spara en ny revision, eller markera ett block och be experten ändra det med röst eller text.

Varje sparad revision behåller sina källreferenser. Om dokumentet har ändrats sedan en revidering startade visas en revisionskonflikt så att den nyare texten kan granskas. **Word** och **PDF** exporterar den sparade revision som visas. PDF-export kräver att serverns dokumentkonvertering är tillgänglig.

Knappen **Minnen** i chatthuvudet öppnar expertens minneslogg för det workspace som är valt. Där kan du läsa, redigera, ta bort eller rensa minnen inom samma workspace. Andra klienters minnen ingår inte.

Verktygsikonen i samma chatthuvud öppnar expertchattens verktygsval. Kryssa i vilka bolags-, sök-, research- och kollegieverktyg experten får använda. Ändringen sparas direkt för experten. En expert som saknar ett verktyg använder det inte i chatten. **Slå upp tidigare research** hämtar fryst research som redan finns för kunden när experten behöver den. Den startar ingen ny research.

Med verktyget **Fråga en annan expert** kan experten lämna vidare en fråga som ligger utanför den egna kompetensen. Experten säger först med egna ord att hen frågar en kollega. En kunnig kollega svarar då i sin egen konversation med vem som frågade, den omformulerade frågan och sitt svar. Kollegans svar vävs in i nästa replik, eller kommer som ett nytt meddelande om du väntar. Båda experterna minns frågan och svaret. Om ingen kollega har rätt kompetens får du ett tydligt besked.

Den runda expertikonen i listan eller i chatthuvudet öppnar expertens profilfält i en modal ovanpå chatten — samma vänsterkolumn som i Due Diligence (kompetens, bakgrund, anekdot, verktyg och spara). Du kan också ladda upp en profilbild som visas i listan och chatten. Chatten och presentationsläget ingår inte. Klicka på namn eller förhandsvisning i listan för att öppna konversationen.

När en expert startar research skapas ett vanligt bakgrundsjobb. Research-ikonen (mikroskop) uppe till höger visar pågående och avslutade research-jobb i en lista. Välj ett jobb för att följa det i en modal. Portföljikonen bredvid öppnar alla bakgrundsjobb. Grafikonen till vänster om research-ikonen öppnar kunskapsgrafen. Den syns för administratörer. Om researchen avbryts, till exempel vid en serveromstart, öppnar du jobbet och väljer **Återuppta research**. Den fortsätter från det som redan hunnit sparas. Om researchen blev klar men resultatet blev fel väljer du **Kör om research**. Det startar en ny research med samma fråga.

Juridisk research kan söka lagtext, svenska domstolsavgöranden och förarbeten via lagen.nu. När frågan gäller hur ett visst lagrum har tillämpats kombineras en sökning på den konkreta frågan med avgöranden som hänvisar till lagrummet. Relevanta avsnitt i förarbeten prioriteras framför dokumentets inledning. Uppladdat material används inte som extern researchkälla.

Om flera researchbehov hittar samma exakta källavsnitt visas det som en gemensam källa med flera behovskopplingar. Olika relevanta avsnitt ur samma dokument visas fortfarande var för sig.

## Öppna företagets tidigare expertintervju

I företagets workspace öppnar **Intervju** expertens tidigare samtal i en dialog. Där finns den äldre historiken, bildbilagor, föreslagna följdfrågor och åtgärder för tidigare meddelanden. Ett pågående röstsamtal avslutas innan dialogen öppnas. Stäng dialogen för att återgå till workspace-chatten.

## Chatta med en expertpanel

Öppna **Grupper** och välj en expertpanel. Gruppikonen längst till vänster i huvudet öppnar **Expertpaneler** i en ruta. Experterna där är samma som i chattlistan. Skapa en panel och välj **Starta gruppchatt**, eller skapa panelen så öppnas chatten direkt. När du skickar en fråga svarar panelens experter var för sig. Expertens namn visas ovanför respektive svar. Telefonikonen till höger i skrivfältet startar röstsamtalet, på samma plats som i en enskild chatt. Det du säger skrivs ut i chatten. Experter som inte tilltalas vid namn räcker upp handen. Välj en hand för att ge den experten ordet. **Rensa chatt** tar bort panelens meddelanden.

På en mindre skärm visas chatten eller arbetsytan åt gången. Växla med **Chatt** och **Workspace** och öppna chattlistan med förstoringsglaset.

## Användarmenyn

Dina initialer eller profilbild visas längst upp till höger. Klicka på dem för att öppna menyn. **Min profil** öppnar profilredigering i en modal ovanpå chatten — samma innehåll som i admin, utan att lämna SME. **Logga ut** ligger längst ned.

Administratörer ser även **Admin**. Det öppnar den vanliga vyn **Verktyg** i en stor modal ovanpå SME-chatten. Stäng modalvyn för att återgå till chatten.

## Bakgrundsjobb

Portföljikonen i SME-huvudet öppnar **Bakgrundsjobb** i en modal ovanpå chatten. Där syns researchjobb och dokumentutkast som en expert har startat, med status pending, running, succeeded eller failed. En siffra på ikonen visar hur många jobb som fortfarande pågår. Ett färdigt dokumentutkast öppnas i arbetsytan när jobbet blir klart. Om det inte gör det väljer du **Öppna utkast**. Ett misslyckat expertresearch-jobb kan återupptas från listan. En avslutad expertresearch kan köras om och startar då som ett nytt jobb.

## Kunskapsgraf

Administratörer har en grafikon till vänster om research-ikonen. Den öppnar kunskapsgrafen i en stor modal ovanpå chatten. Växla mellan **Kunskap** och **Minne**, välj en etikett och öppna en nod. Där syns text, egenskaper och kopplingar till andra noder. Sökningen matchar nyckel och text. Stäng modalen för att återgå till chatten.

## Relaterade guider

- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
- [Skapa och redigera expert](skapa-och-redigera-expert.md)
