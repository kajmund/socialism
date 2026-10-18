# Structure-aware embeddings, A vs B

Dense document-local ranking on 40 development documents,
84 spanned cells. Search is not evidence. No Jev. No C.
Default stays D.

| Variant | hit@3 | hit@5 | hit@10 | MRR | Hard-neg@5 | Off-gold@5 | Embed tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 95% | 96% (81/84) | 96% | 0.765 | 0.02 | 3.82 | 57517 |
| B | 94% | 96% (81/84) | 99% | 0.782 | 0.02 | 3.81 | 105506 |

Same three misses at k=5. B moved two auto-renewal
golds into top-10, not into the candidate budget.
Hard negatives did not change. Index vectors are the
same size. B used about twice as many embedding tokens.

B is not a retrieval win at k=5. **Rejected** as the
Tabular search representation. Original embeddings stay.
Do not run C automatically.

## What this is not

- Not a Jev run.
- Not representation C.
- Not a default change.
- Not a new OverGraph write.
- Not a retune to the four known Dense misses.
