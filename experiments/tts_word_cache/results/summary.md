# TTS repetition analysis — segment level vs word level

Generated deterministically by `analyze.py` from the checked-in corpus. Offline; no API calls.

## Headline numbers

| Level | Total | Unique | Repeated instances | Call share saved | Char share saved |
| ----- | ----- | ------ | ------------------ | ---------------- | ---------------- |
| Segments (cache unit) | 3019 | 2954 | 65 | 2.2 % | 2.6 % |
| Words (theoretical ceiling) | 34820 | 4737 | 30083 | 86.4 % | 89.0 % |

Words, alpha-only tokens (numbers/dates excluded): 33578 total,
4600 unique, repeat call share 86.3 %.

Segments a perfect word cache could serve entirely from cached words (every token seen
before in the corpus): 1795 of
3019
(59.5 %) — assuming perfect splicing
and ignoring prosody.

## Domain core (live-voice domain; operator manuals excluded)

| Level | Total | Unique | Repeated instances | Call share saved | Char share saved |
| ----- | ----- | ------ | ------------------ | ---------------- | ---------------- |
| Segments (cache unit) | 541 | 536 | 5 | 0.9 % | 0.9 % |
| Words (theoretical ceiling) | 4782 | 1760 | 3022 | 63.2 % | 65.7 % |

Segments a perfect word cache could serve entirely from cached words:
126 of 541
(23.3 %).

## Per source

| Source | Texts | Chars | Segments | Unique seg. | Seg. repeat | Words | Unique words | Word repeat |
| ------ | ----- | ----- | -------- | ----------- | ----------- | ----- | ------------ | ----------- |
| sme-story | 83 | 10727 | 192 | 190 | 1.0 % | 1479 | 641 | 56.7 % |
| golden-questions | 200 | 11907 | 200 | 200 | 0.0 % | 1767 | 697 | 60.6 % |
| sme-docs | 2 | 9719 | 82 | 82 | 0.0 % | 1241 | 656 | 47.1 % |
| operator-manuals | 75 | 223418 | 2478 | 2418 | 2.4 % | 30038 | 3496 | 88.4 % |
| backend-tests | 64 | 1753 | 67 | 64 | 4.5 % | 295 | 167 | 43.4 % |

## Top repeated segments

1. `3. Växla mellan Rutnät och Lista .` — 4×
2. `2. Medan rapporten genereras uppdateras sidan automatiskt.` — 3×
3. `De svarar på det som just sades och upprepar inte en genomgång som redan getts.` — 3×
4. `Din markering är gul och visar ditt namn.` — 3×
5. `En expert kan skriva en kommentar tillsammans med sin markering.` — 3×
6. `Experterna ser vem som har markerat vilken passage.` — 3×
7. `Sidnumret följer den sida som syns.` — 3×
8. `- Sök — webbsökning (DuckDuckGo) och Wikipedia.` — 2×
9. `2. Expandera ett försök och bläddra i Flödet .` — 2×
10. `3. Bekräfta med Ta bort?` — 2×

## Top words

och (1142×), i (969×), en (794×), du (528×), som (472×), eller (383×), kan (361×), på (357×), till (336×), om (331×)

## Interpretation

- A segment-level cache saves 2.2 % of TTS calls and
  2.6 % of billed characters on a warm cache. In the
  live-voice domain core the segment repeat rate is even lower
  (0.9 % calls / 0.9 % chars).
- A perfect word-level cache could at most save 86.4 % of
  word synthesis calls (89.0 % of characters), and only
  1795 of 3019
  segments (59.5 %) would become fully
  cache-served — and each must be reassembled from isolated or aligned word audio
  (destroyed or mismatched prosody, see docs/guides/tts-word-cache.md). The ceiling is
  therefore not reachable at acceptable quality; the segment cache captures the
  reachable part with zero audio surgery.
