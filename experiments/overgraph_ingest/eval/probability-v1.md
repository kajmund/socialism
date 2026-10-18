# Tabular Jev probability P1

P0 prompt. Frozen hybrid top-5. One Jev call per cell. Score does not change status. P2 is not implemented.

## A. Inventory

- API fields: `confidence` (chosen) and `probabilities` (all alternatives).
- `score_type`: `jev_choice_confidence`. P1 uses status `confidence`.
- Classification distribution, not a token logprob, not legal correctness.
- `answer_cell` can read it from the existing response. Frozen tabular baselines do not contain it, so this is a live observation, not a replay.
- Observed answer fields: `['choice', 'confidence', 'probabilities', 'type']`.
- Live score present: `True`.

C@8 already found the same field unstable across identical classify runs. A fixed cutoff is not a calibrated probability.

## B. Score versus correctness

| True ANSWERED | n | min | median | mean | max |
|---|---:|---:|---:|---:|---:|
| score | 20 | 0.33 | 0.99 | 0.898 | 1.0 |
| False ANSWERED | n | min | median | mean | max |
|---|---:|---:|---:|---:|---:|
| score | 17 | 0.18 | 0.94 | 0.7729411764705882 | 1.0 |

False-answer mean lower: `True`.
Ranges overlap: `True`.
True ANSWERED goes down to 0.33. False ANSWERED goes up to 1.0, including Avtal 13 citing settlement secrecy.

## C. Calibration

Usable separation: `False`.
P2 was not implemented.

## D–E. Quality and cost

Same request as default `answer_cell`. No extra model call. Overhead is parsing `confidence`.

## F. Decision

- Verdict: `keep_explicit_uncertain`.
- Keep explicit UNCERTAIN: `True`.
- Choice confidence overlaps for true and false ANSWERED. It does not replace explicit UNCERTAIN.

Default P0 stays.
