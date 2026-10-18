# Tabular status P0_v2_D repeats

Jev has no temperature parameter. Repeats are the only stochasticity.
Default P0 is unchanged. Does not overwrite `eval/status-v2.md`.

## Unused HARD_NEG are not holdout

The five unused negatives in status-v2 match named `Räknas inte` exclusions written after those error types were seen:

- `hard_neg:Avtal_38:liability-cap` → `in_distribution:vite`
- `hard_neg:Avtal_70:confidentiality` → `in_distribution:avtalets_innehall`
- `hard_neg:Avtal_14:auto-renewal` → `in_distribution:tills_vidare`
- `hard_neg:Avtal_19:notice-period` → `in_distribution:havning_huvudavtal`
- `hard_neg:Avtal_45:auto-renewal` → `in_distribution:tills_vidare`

## Unseen holdout

These near-misses were chosen because their wording is not a named D exclusion. The exclusions were written without seeing these errors.

- `holdout:Avtal_35:auto-renewal` → `unseen:optional_renewal_right`
- `holdout:Avtal_92:liability-cap` → `unseen:settlement_no_further_claims`
- `holdout:Avtal_20:liability-cap` → `unseen:liability_insurance`
- `holdout:Avtal_76:liability-cap` → `unseen:abl_statutory_liability`
- `holdout:Avtal_52:liability-cap` → `unseen:hold_harmless_product_insurance`

## Spread on the 23 prompt-scored cells

| Mått | min | median | max | per körning |
|---|---:|---:|---:|---|
| True ANSWERED | 11 | 11 | 11 | [11, 11, 11, 11, 11] |
| False ANSWERED | 0 | 0 | 0 | [0, 0, 0, 0, 0] |
| Missade svar | 0 | 0 | 0 | [0, 0, 0, 0, 0] |

## Spread on unseen holdout

| Mått | min | median | max | per körning |
|---|---:|---:|---:|---|
| True ANSWERED | 0 | 0 | 0 | [0, 0, 0, 0, 0] |
| False ANSWERED | 1 | 1 | 1 | [1, 1, 1, 1, 1] |
| Missade svar | 0 | 0 | 0 | [0, 0, 0, 0, 0] |

## Unstable cells

None. Every cell returned the same status on all repeats.

## Cells with any false ANSWERED

- `holdout:Avtal_92:liability-cap`

## Verdict

Eleven true `ANSWERED` on the 23 prompt-scored cells is stable (11/11/11 across five repeats, zero spread). It is not a lucky single run.
The five unused HARD_NEG are in-distribution for named exclusions, so they do not show generalization.
On unseen holdout D false-answered Avtal 92 in 5/5: a settlement release (`inga ytterligare krav`) was taken as a liability cap. That wording is not a named D exclusion.
D did not generalize. Default P0 stays.
