# Multiple answers per cell

Dense k=5. Same five TextUnits. One Jev.
Single keeps P0. Multi lists distinct listed excerpts.
Reserved holdout unused. Default stays D.

| Variant | Gold hits | Extras | Multi-span hits | Multi-span extras |
|---|---:|---:|---:|---:|
| single | 65/101 | 2 | 32/65 | 0 |
| multi | 79/101 | 11 | 46/65 | 4 |

Changed cells: 21/120.
Cells with more gold hits: 13.
Cells with more extras: 8.

Jev can return several cited answers in one call. On multi-span cells it found more gold, and it also added extras. That is not an unfiltered quality win.

Multi-answer evidence only. A model that adds extras has not improved quality. Default stays D. Do not start the Socialism table from this run.

## What this is not

- Not a retrieval change.
- Not heading metadata.
- Not the reserved holdout.
- Not the Socialism product table.
