# Tabular Review user gold

The user question is the contract.
Retrieval gold, user questions, and P0 are unchanged.
No new Jev run. Frozen D, E, and K are rescored offline.
Historical 78% / 54% remain passage-gold benchmarks only.

## What each question means

### auto-renewal

Asked: Förlängs avtalet automatiskt?

Whether the agreement continues or starts a new period without the parties signing a new agreement.

Old notes excluded tills vidare and conversion. The user question does not.

### notice-period

Asked: Vilken uppsägningstid gäller enligt avtalet?

Which notice period or periods apply, and to what.

Old gold wanted a standing terminate-the-agreement term. Notice that stops auto-renewal, optional early exit, and immediate end of a framework also answer the user.

### liability-cap

Asked: Finns det en begränsning av parternas skadeståndsansvar?

Whether the parties' damages liability is limited, how, and with what exceptions.

The user asked about limitation, not only a named cap clause.

### confidentiality

Asked: Finns det en sekretessplikt i avtalet?

Whether this agreement creates a duty to keep information secret, who, and for how long.

Old relevant_units omitted some operative NDAs. Absence there is not a no.

### liability-secrecy-carveout

Asked: Undantas brott mot sekretess från ansvarsbegränsningen?

Whether a liability limitation excludes a secrecy breach, and which provision says so.

This question already matched the old gold relation.

## Frozen variants against this gold

78% and 54% stay as passage-gold history. They are not
user-question quality.

| Variant | Passage gold | User gold | True | False | Miss | Empty | Uncertain |
|---|---:|---:|---:|---:|---:|---:|---:|
| D | 78% | 84% (84/100) | 33 | 4 | 11 | 51 | 1 |
| E | 74% | 90% (90/100) | 44 | 6 | 2 | 46 | 2 |
| K | 73% | 90% (90/100) | 43 | 6 | 3 | 47 | 1 |

Against passage gold D beat E and K. Against the user
question E and K beat D. D still misses several operative
secrecy duties that were never in retrieval gold.

## By question (D)

| Question | True | False | Miss | Empty | Uncertain |
|---|---:|---:|---:|---:|---:|
| auto-renewal | 9 | 1 | 2 | 8 | 0 |
| notice-period | 11 | 0 | 2 | 6 | 1 |
| liability-cap | 5 | 0 | 1 | 14 | 0 |
| confidentiality | 5 | 3 | 6 | 6 | 0 |
| liability-secrecy-carveout | 3 | 0 | 0 | 17 | 0 |

## What this is not

- Not a rewrite of retrieval gold.
- Not a new prompt or retrieval setting.
- Not a reason to keep 78% as Tabular Review quality.
