# TTS word-cache investigation

Offline, deterministic analysis answering: *can we cache individual words in the
ElevenLabs TTS cache, or should we cache at phrase level?* The evidence and the
recommendation live in [docs/guides/tts-word-cache.md](../../docs/guides/tts-word-cache.md).
The phrase-level cache itself is built separately (see `docs/guides/tts-cache.md`).

## Files

| File | What it is |
| ---- | ---------- |
| `analyze.py` | Runs the corpus through the production `SpeechSegmenter` (first_target=110, max_chars=220) and computes segment-level and word-level repetition statistics. |
| `results/analysis.json` | Machine-readable results (checked in, deterministic). |
| `results/summary.md` | Human-readable summary generated from the JSON (checked in). |

## Run it

```bash
cd backend
uv run python ../experiments/tts_word_cache/analyze.py
```

The script only imports the backend's `app.services.speech_segmenter` (stdlib-only
module). No network, no API keys, no randomness. Run it twice and diff the results to
verify determinism — the outputs are byte-identical by construction.

## Corpus sources (documented in the script)

| Group | Source | Contents |
| ----- | ------ | -------- |
| `sme-story` | `synthetic_sme/ground_truth/truth_model.json` (`events[].title` + `events[].description`) and `synthetic_sme/generator/data/facts.json` (`anomalies[].description`) | 83 Swedish business story texts — the domain language of the SME live voice chat. |
| `golden-questions` | `synthetic_sme/golden_questions/golden_questions.json` | 200 Swedish questions users actually voice-ask the assistant. |
| `sme-docs` | `synthetic_sme/README.md`, `synthetic_sme/validation/validation_report.md` | Swedish business prose. |
| `operator-manuals` | `knowledge/manual/*.md` (75 files) | Swedish operator guides. Included as the *upper bound* of repetitive instructional text; not the voice-chat domain, reported separately. |
| `backend-tests` | String literals in 19 curated voice/SME/workspace test files | Swedish answer-like strings extracted via AST (≥3 words, ≥2 Swedish markers). |

The four first groups form the **domain core** used for the headline recommendation.

## Metrics computed

- **Segment level** (the phrase cache unit): total/unique segments, repeated
  instances, repetition rate by *calls* and by *characters* (ElevenLabs bills per
  character), top repeated segments.
- **Word level** (theoretical ceiling for a word cache): same rates on whitespace
  tokens, alpha-only subset (numbers/dates excluded), top 20 words, and
  **fully-assemblable segments** — segments whose every token has been seen before,
  i.e. the share of segments a perfect word cache could serve with zero new synthesis
  (ignoring prosody and splicing costs).

## Headline result

| | Full corpus | Domain core |
| - | ----------- | ----------- |
| Segment repetition (calls / chars) | 2.2 % / 2.6 % | 0.9 % / 0.9 % |
| Word repetition (calls / chars, ceiling) | 86.4 % / 89.0 % | 63.2 % / 65.6 % |
| Segments a perfect word cache could fully serve | 59.4 % | 23.1 % |

Repeated words reappear inside almost-unique segments, so a word cache must splice
nearly every reply from pieces with degraded prosody — while the phrase cache captures
the actually-repeatable unit with zero audio surgery. See the guide for the full
argument and the ElevenLabs API facts.
