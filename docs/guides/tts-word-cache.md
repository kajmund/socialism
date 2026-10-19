# TTS caching: phrase level vs word level

Live voice streams assistant answers to ElevenLabs one `SpeechSegmenter` segment at a
time (~110–220 chars, phrase/sentence boundaries). The segment cache
([tts-cache.md](tts-cache.md)) keys on exactly those segments. This guide answers the
follow-up question: **can we cache individual words instead, and should we?**

Short answer: no. Evidence and reasoning below. Reproduce all numbers offline with
`experiments/tts_word_cache/analyze.py` (see
[experiments/tts_word_cache/README.md](../experiments/tts_word_cache/README.md)).

## What the numbers say

`analyze.py` runs a documented Swedish corpus (SME business story texts, the 200 golden
questions users voice-ask, SME docs, operator manuals as a repetitiveness upper bound,
and Swedish answer strings from backend tests) through the production segmenter and
measures repetition at segment level and at word level.

| Metric | Full corpus | Domain core (voice-chat sources only) |
| ------ | ----------- | ------------------------------------- |
| Segments: repeated share of TTS calls | 2.2 % | 0.9 % |
| Segments: repeated share of billed characters | 2.6 % | 0.9 % |
| Words: repeated share of word instances (ceiling) | 86.4 % | 63.2 % |
| Words: repeated share of characters (ceiling) | 89.0 % | 65.6 % |
| Segments a perfect word cache could serve entirely from cached words | 59.4 % | 23.1 % |

The pattern is decisive: **high word repetition, near-zero segment repetition.** Words
recur constantly, but they recur inside different, mostly unique segments (the domain
core has 536 unique segments out of 541). A word cache would therefore have to assemble
almost every reply from pieces; a segment cache serves the unit that actually repeats.
Even under the generous assumption that every repeated word is spliceable with perfect
audio, only 23.1 % of domain-core segments could be fully assembled from a warm word
cache — and every one of them would still need the splice. The top repeated words are
function words whose realization varies the most with context: `och` (1142×), `i` (969×),
`en` (794×), `du` (528×), `som` (472×).

## Why spliced or isolated words sound wrong

There are two ways to cache word audio, and both break Swedish prosody.

**Isolated word synthesis** (one TTS call per word): the model renders the citation
form, with no phrase context.

**Splicing from a rendered sentence**: generate the full sentence once, cut the PCM at
word boundaries, cache the slices, concatenate on reuse.

Both fail for the same underlying reasons:

- **Accent 1 vs accent 2.** Swedish distinguishes words by pitch accent that depends on
  word form and context: *anden* (the duck, accent 1) vs *anden* (the spirit, accent 2),
  *banan* (the track) vs *banan* (the fruit), *tomten* (the yard) vs *tomten* (Santa).
  A cached single word must commit to one accent; the surrounding sentence is what
  disambiguates the other reading. Background: [Swedish phonology](https://en.wikipedia.org/wiki/Swedish_phonology).
- **Coarticulation across word boundaries.** Speech blends sounds over word edges;
  Swedish retroflexion makes *för sent* ≈ [fœˈʂeːnt] and *har sagt* ≈ [ha ˈʂakt]. A word
  sliced from one context carries the neighbors' influence into the next context.
- **Connected-speech reductions.** TTS reduces function words contextually: *och* → *å*,
  *de/dem* → *dom*, *är* → *e*, *något* → *nåt*. An isolated or re-spliced function word
  tends to come out over-articulated, making assembled speech sound list-like — and
  these are exactly the top-repeated words.
- **Phrase-final lengthening and boundary tones.** The last syllable of a phrase is
  lengthened and carries a boundary tone (fall for statements, list intonation in
  enumerations, rise for questions). A cached word recorded phrase-finally keeps that
  lengthening and fall when placed phrase-medially; a word recorded medially sounds
  abruptly cut at a phrase end.
- **Focus and F0 declination.** The same surface word is stressed or reduced depending
  on information structure, and pitch declines across an utterance. Splicing words from
  different utterances produces pitch jumps at every join; level normalization fixes
  volume, not contour.

A segment, by contrast, is synthesized as a whole: its internal prosody (accents,
coarticulation, reductions, phrase-final contour) is consistent by construction. The
segment cache replays that intact unit.

## ElevenLabs API facts

- **TTS timestamps are character-level, not word-level.** The
  [stream with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps)
  endpoint (SDK 2.26.0: `text_to_speech.convert_with_timestamps` /
  `stream_with_timestamps`) returns `alignment` with `characters`,
  `character_start_times_seconds`, `character_end_times_seconds`, plus
  `normalized_alignment`. Word boundaries must be derived client-side from characters
  and whitespace. ElevenLabs staff confirmed word-level alignment is not supported:
  [elevenlabs-python issue #556](https://github.com/elevenlabs/elevenlabs-python/issues/556)
  ("you can get the timings of each word yourself using the character based alignment").
- **Forced Alignment aligns existing audio, not text.** `POST /v1/forced-alignment`
  ([capability](https://elevenlabs.io/docs/overview/capabilities/forced-alignment),
  [API reference](https://elevenlabs.io/docs/api-reference/forced-alignment/create))
  returns word timestamps with confidence (`loss`), billed at the Speech-to-Text rate.
  It cannot produce word audio from text alone: you would still render the full sentence
  with TTS first, then pay for alignment to cut it up — extra cost on every sentence you
  want to splice.
- **The API's own continuity mechanism is contextual generation, not splicing.** The
  TTS request accepts `previous_text`, `next_text`, `previous_request_ids`,
  `next_request_ids` explicitly to "improve the speech's continuity when concatenating
  together multiple generations" ([stream with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps)).
  The vendor's supported way to keep prosody across unit boundaries is to generate each
  unit with context — i.e. to generate the unit whole.
- **`seed` is best-effort only** ("Determinism is not guaranteed"), so word slices cut
  from separate generations of the same sentence may still differ, complicating splice
  matching further.

## Cost and latency

| | Segment cache (phrase level) | Word cache |
| - | --------------------------- | ---------- |
| Hit saves | One streaming TTS call, its billed characters (ElevenLabs bills per character), and the API/network latency before audio; playback streams the cached file immediately. | At most the characters of the repeated words; a miss still needs a full sentence render, so savings only materialize for fully assemblable segments (23.1 % of domain-core segments, at best). |
| Miss cost | One TTS call (unchanged). | One TTS call plus alignment, slicing, and indexing work — more expensive than today. |
| Extra latency | None; disk read. | Decode-with-timestamps JSON chunks, derive word boundaries, slice, crossfade — all before the first audio byte can stream. |
| Added complexity | Hash lookup + file stream. | A second API surface, PCM slicing, a crossfade/pitch-normalization engine, and a per-word index — to serve audio whose quality is worse. |

The character-level ceiling (89 % of characters are in repeated words) is therefore
misleading: it counts word instances, not servable segments, and reaching it costs
naturalness in a product whose core value is live spoken conversation.

## Recommendation

**Cache at phrase/segment level** — the units `SpeechSegmenter` already produces and
`tts-cache.md` implements. The measured segment repetition (2.2 % full corpus, 0.9 %
domain core) is the genuinely captureable traffic, and phrase-level replay preserves
prosody with zero audio surgery.

Revisit word-level caching only if **all** of the following hold:

1. ElevenLabs adds word-level timestamps to the TTS timing endpoints (not supported
   today; tracked in [issue #556](https://github.com/elevenlabs/elevenlabs-python/issues/556)),
   or a word-cache experiment limits itself to short canned tokens (numbers, dates,
   names) that dominate real repeated-segment traffic.
2. A benchmark shows a material share of *segments* (not word instances) that a warm
   word cache could serve fully — using the `segments_fully_assemblable` metric in
   `experiments/tts_word_cache/analyze.py` on live traffic.
3. A listening test accepts spliced output: render one segment fresh, assemble the same
   text from cached words with crossfade, and compare. Until then, assume the splice
   loses.

## Conclusion

Word-level caching for ElevenLabs TTS is a textbook case of a high theoretical ceiling
with no practical payoff: repeated words hide inside unique segments, word-level
alignment is not offered by the API, and both splicing and isolated synthesis destroy
Swedish prosody. Cache at phrase level; treat word-level as a conditional future
experiment, not a plan.
