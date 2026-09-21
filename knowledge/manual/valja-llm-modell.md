---
type: guide
title: Välja LLM-modell
description: Så skapar du LLM-konfigurationer, sätter default och kopplar dem till enskilda prompter.
tags: [grunddata, jobb]
---

# Välja LLM-modell

Under **Verktyg** → **LLM** skapar du namngivna **LLM-konfigurationer**. Varje konfiguration har samma inställningar som tidigare: modell, temperatur, top P, max tokens och reasoning effort.

**En** konfiguration är **default**. Alla prompter använder den tills du väljer en annan konfiguration på just den prompten under **Verktyg** → **Konfigurationer**.

**OASIS** (simulering) påverkas inte — den fortsätter använda DeepSeek.

## Skapa och redigera konfigurationer

1. Öppna **Verktyg** → **LLM**.
2. Klicka **Ny konfiguration** eller välj en sparad i listan.
3. Ge den ett **Namn**.
4. Välj en av profilerna:
   - **DeepSeek Flash** — `deepseek-flash`
   - **DeepSeek V4 Pro** — `deepseek-v4-pro`
   - **OpenAI GPT OSS** — Cerebras `gpt-oss-120b`
   - **Qwen 3.8 27B** — Cerebras `qwen-3.8-27b`
5. Justera parametrar som visas för vald modell:
   - **Temperatur** och **Top P** (alla modeller)
   - **Max tokens** (DeepSeek upp till 393 216; Cerebras GPT OSS och Qwen upp till 40 000)
   - **Reasoning effort**:
     - DeepSeek: `none` / `low` / `high` / `max` (`none` stänger av thinking)
     - Cerebras GPT OSS och Qwen: `low` / `medium` / `high`
6. Klicka **Spara konfiguration**.

Den första konfigurationen blir automatiskt default. För en senare konfiguration: öppna den och klicka **Sätt som default**. Default kan inte tas bort — byt default först.

Om API-nyckel saknas för leverantören visas ett fel och du kan varken spara eller köra probe.

Ändringen av default gäller direkt i den körande backend-processen. Vid omstart läses default från databasen (annars gäller miljövariablerna).

## Koppla en konfiguration till en prompt

1. Öppna **Verktyg** → **Konfigurationer** och redigera en konfiguration.
2. Under **Innehåll & ton** väljer du ett promptfält.
3. I **LLM-konfiguration** väljer du default eller en namngiven konfiguration.
4. Valet sparas direkt och gäller **alla kunder** — inte bara den konfiguration du redigerar.

Nya och befintliga prompter använder default tills du byter.

## Bild i personachatt

DeepSeek Flash och Qwen kan ta emot bilder i personachatten och körningsintervjun. DeepSeek V4 Pro och GPT OSS är text-only — då visas ingen bildknapp. Qwen tar bara PNG och JPEG. Bildknappen följer **default**-konfigurationen.

## Probe med statistik

Använd **Probe** för att skicka en testprompt mot den valda konfigurationen (utan att behöva spara först om du skickar med aktuell draft via UI).

Efter körning visas bland annat:

- **Round-trip** — hela svarstiden
- **TTFT** — tid till första token
- **Tokens/s** — completion-tokens per sekund
- Tokenräkning (prompt / completion / totalt)
- Finish reason och svarstexten

## Relaterade guider

- [Hantera konfigurationer](hantera-konfigurationer.md)
- [Använda playground](anvanda-playground.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
