---
type: guide
title: Inspektera en execution-körning
description: Läs en Run och dess historiska Attempts, evidence och resultat. Inget redigeras här.
tags: [korningar, rapporter]
---

# Inspektera en execution-körning

En **execution-körning** är inte samma sak som en simuleringskörning under **Körningar**. Den öppnas via en direktlänk, inte från vänstermenyn. Sidan är bara läsning.

## Vad du ser

Överst står körningens namn, modul, när den skapades och uppdaterades, och ärendenummer om det finns.

Därunder ligger **Attempts** i tidsordning. Varje rad visar typ, status, när den skapades, om den bygger på ett tidigare attempt, hur många evidence-poster som hittades eller saknas, och om ett resultat är sparat.

Status kan vara skapad, research, redo, pågår, klar eller misslyckad.

## Välj ett attempt

1. Klicka på det attempt du vill läsa.
2. Du ser tre block med det som var fryst då: **Input**, **Konfiguration** och **Research**.
3. För generic panel lyfts ämne, brief, max antal ronder och expertplatser fram. Researchplanen visar frågan, varför den behövs, vem som bad om den och vilka källtyper som efterfrågades.

## Evidence

Evidence är det underlag attemptet faktiskt såg. En fryst uppsättning visar tidpunkten och posterna i den sparade ordningen.

Varje post kan vara **hittad**, **ej hittad** eller **fel**. Hittade poster har en etikett som `[E1]`. Finns en käll-URL kan du öppna den. **Provenance** fäller ut mer om var posten kom ifrån.

Saknas evidence är det normalt — inte ett fel.

## Resultat

När ett resultat är sparat för generic panel ser du **Sammanfattning**, **Påståenden**, **Dissensus** och **Obesvarat**.

Fryst evidence gör inte en expert kompetent. Om panelen saknar rätt sakkompetens för frågan lämnas den obesvarad — även när underlaget ser utmärkt ut. En kompetent expert som avstår är inte samma sak som saknad kompetens.

Ett påstående kan peka på evidence med `[E1]`. Klicka på en känd referens för att hoppa till det kortet. En okänd referens markeras som olöst och kraschar inte sidan.

## Misslyckade attempts

Ett misslyckat attempt döljer inte historiken. Du kan fortfarande läsa input, konfiguration, researchplan och det evidence som hann sparas.

Du kan inte skapa, köra om, redigera eller ta bort något på den här sidan.
