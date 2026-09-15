---
type: guide
title: Förstå lexikal konvergens i simulering
description: Så tolkar du kvalitetsvarningar när många agenter använder samma fraser i simuleringsresultat.
tags: [korningar]
---

# Förstå lexikal konvergens i simulering

Efter en avslutad simulering kan du få en varning om **lexikal konvergens** högst upp på **Resultat**-fliken. Den visar att många agenter i populationen använder samma ord eller fraser — ofta tecken på att språket ekar injektionstext, budskap eller andra gemensamma källor i stället för att vara spontant.

Varningen stoppar inte simuleringen och påverkar inte rapportbeställning. Den hjälper dig bedöma om resultatet är trovärdigt nog att tolka eller beställa rapport på.

## När varningen visas

1. Öppna körningen och gå till fliken **Resultat** när minst ett försök är klart.
2. Om populationen delar fraser som når tröskeln (minst hälften av agenterna) visas en gul ruta med rubriken **Lexikal konvergens**.
3. Sammanfattningen anger hur många fraser som flaggats och hur många agenter populationen har.
4. Varje rad visar frasen i citattecken, hur många agenter som använt den, andel i procent, och om frasen klassas som **eko av injektion** eller **gemensam fras**. Vid eko kan källan (till exempel vilket budskap) visas.

Visas fler än åtta fraser listas de första åtta och en rad anger hur många som döljs.

## Stimulus vs kontroll

Har körningen både **stimulus** (med injektion) och **kontroll** (utan) visas en extra blå ruta **Stimulus vs kontroll** ovanför eller bredvid varningslistan:

1. Den jämför antalet konvergensvarningar i stimulus- respektive kontrollvarianten.
2. Fler varningar i stimulus än i kontroll tyder ofta på att injektionstext eller budskapsspridning driver fraserna.
3. Fler i kontroll än stimulus är ovanligt — granska populationens spontana språkmönster.
4. Samma antal i båda varianterna tyder på att konvergens inte enbart kommer från injektionen.
5. Frasor som bara finns i stimulus listas separat med hur många agenter som använt dem.

## Vad du kan göra

- Läs igenom flaggade fraser i flödet och avgör om de påverkar tolkningen.
- Vid tydlig eko av budskap: prova annat budskap, färre injektioner eller en annan population.
- Jämför stimulus och kontroll innan du drar slutsatser om injektionens effekt.
- Beställ rapport som vanligt om varningen känns acceptabel — se [Beställa en rapport](bestalla-rapport.md).

## Relaterade guider

- [Läsa simuleringsresultat](lasa-simuleringsresultat.md)
- [Reaktionsmodell i simulering](reaktionsmodell-i-simulering.md)
- [Skapa en ny körning](skapa-korning.md)
- [Beställa en rapport](bestalla-rapport.md)
