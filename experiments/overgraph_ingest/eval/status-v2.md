# Tabular status P0_v2

Nearby topical units are scored as `UNCERTAIN`.
False `ANSWERED` is the costlier error.
Default P0 is unchanged.

| Steg | True ANSWERED | False ANSWERED | Missade svar | True UNCERTAIN | True NOT_FOUND | Statusfel |
|---|---:|---:|---:|---:|---:|---:|
| P0 | 10 | 7 | 0 | 1 | 4 | 1 |
| P0_v2_B | 10 | 4 | 0 | 5 | 2 | 2 |
| P0_v2 | 10 | 4 | 0 | 5 | 2 | 2 |
| P0_v2_D | 11 | 0 | 0 | 8 | 2 | 2 |
| P0_v2_en | 11 | 1 | 0 | 7 | 2 | 2 |

## Vad varje steg bidrog med

- **A / P0.** Baslinje. Sju falska `ANSWERED`, däribland Avtal 09, 17 och 13.
- **B.** Nya statusdefinitioner. Avtal 09 och 17 blev `UNCERTAIN`. Tre hårda negativer var oförändrade. Avtal 13 valde fortfarande 6.3.
- **C.** Beslutsträdet ändrade inte huvudmängden mot B. Permutation: 6.1 bara när den låg först.
- **D.** Skarpare frågor. Noll falska `ANSWERED`. Avtal 13 valde 6.1 i 5/5 permutationer. Inga missade sanna `ANSWERED`.
- **E.** Engelska D. Ett kvarvarande falskt `ANSWERED` (Avtal 19, uppsägningstid / huvudavtal). Sämre än svensk D.

Avtal 13 på hybrid saknade 6.1 och räknas som retrievalfel.
Default `answer_cell` är fortfarande P0.

## Acceptans

{
  "repeats": {
    "P0_v2": {
      "error:Avtal_09:liability-cap:dense": {
        "runs": 5,
        "zero_false_answered": true
      },
      "error:Avtal_17:liability-cap:dense": {
        "runs": 5,
        "zero_false_answered": true
      }
    },
    "P0_v2_D": {
      "error:Avtal_09:liability-cap:dense": {
        "runs": 5,
        "zero_false_answered": true
      },
      "error:Avtal_17:liability-cap:dense": {
        "runs": 5,
        "zero_false_answered": true
      }
    }
  },
  "permutations": {
    "P0_v2": {
      "permutations": 5,
      "cited_gold": 1,
      "at_least_4_of_5": false
    },
    "P0_v2_D": {
      "permutations": 5,
      "cited_gold": 5,
      "at_least_4_of_5": true
    }
  },
  "true_answered_regression": {
    "P0": {
      "true_answered_rate": 0.9090909090909091,
      "drop_pp": 0.0,
      "within_2pp": true
    },
    "P0_v2_B": {
      "true_answered_rate": 0.9090909090909091,
      "drop_pp": 0.0,
      "within_2pp": true
    },
    "P0_v2": {
      "true_answered_rate": 0.9090909090909091,
      "drop_pp": 0.0,
      "within_2pp": true
    },
    "P0_v2_D": {
      "true_answered_rate": 1.0,
      "drop_pp": -9.090909090909093,
      "within_2pp": true
    },
    "P0_v2_en": {
      "true_answered_rate": 1.0,
      "drop_pp": -9.090909090909093,
      "within_2pp": true
    }
  },
  "false_answered_09_17_zero": {
    "P0_v2": true,
    "P0_v2_D": true
  }
}
