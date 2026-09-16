---
type: guide
title: Välja LLM-modell
description: Så byter du aktiv chat-modell under Verktyg och mäter latency med en probe.
tags: [grunddata, jobb]
---

# Välja LLM-modell

Under **Verktyg** → **LLM** sätter du vilken chat-modell Socialism använder för personas, panel, expertgranskning, playground-prompts och liknande flöden.

**OASIS** (simulering) påverkas inte — den fortsätter använda DeepSeek.

## Välj modell och parametrar

1. Öppna **Verktyg** → **LLM**.
2. Välj en av profilerna:
   - **DeepSeek Flash** — `deepseek-flash`
   - **DeepSeek V4 Pro** — `deepseek-v4-pro`
   - **OpenAI GPT OSS** — Cerebras `gpt-oss-120b`
   - **Qwen 3.8 27B** — Cerebras `qwen-3.8-27b`
3. Justera parametrar som visas för vald modell:
   - **Temperatur** och **Top P** (alla modeller)
   - **Max tokens** (DeepSeek upp till 393 216; Cerebras GPT OSS och Qwen upp till 40 000)
   - **Reasoning effort**:
     - DeepSeek: `none` / `low` / `high` / `max` (`none` stänger av thinking)
     - Cerebras GPT OSS och Qwen: `low` / `medium` / `high`
4. Klicka **Spara som aktiv**.

Om API-nyckel saknas för leverantören visas ett fel och du kan varken spara eller köra probe.

Ändringen gäller direkt i den körande backend-processen. Vid omstart läses den sparade profilen från databasen (annars gäller miljövariablerna som default).

## Bild i personachatt

DeepSeek Flash och Qwen kan ta emot bilder i personachatten och körningsintervjun. DeepSeek V4 Pro och GPT OSS är text-only — då visas ingen bildknapp. Qwen tar bara PNG och JPEG.

## Probe med statistik

Använd **Probe** för att skicka en testprompt mot den valda konfigurationen (utan att behöva spara först om du skickar med aktuell draft via UI).

Efter körning visas bland annat:

- **Round-trip** — hela svarstiden
- **TTFT** — tid till första token
- **Tokens/s** — completion-tokens per sekund
- Tokenräkning (prompt / completion / totalt)
- Finish reason och svarstexten

## Relaterade guider

- [Använda playground](anvanda-playground.md)
- [Följa bakgrundsjobb](folja-bakgrundsjobb.md)
