# Tabular Review — later phases

v1 is SSR-only. These phases may consume the same review object and
`/tabular-reviews` API. They are separate iterations.

## SWE workflows

Typed workflows can treat a saved review as an input: selected documents,
column definitions, and locked cells. Do not replace the SSR fill path
inside the v1 table. A workflow may *read* cells and enqueue later work.

## Research

Research needs can open the same current `DocumentVersion` TextUnits the
table used. Do not invent a second catalog. Catalog filter stays
deterministic. Tabular Review remains the path for a source-grounded cell.

## Jev verification

A later pass may ask Jev whether a selected verbatim clause *supports* a
column question. That is verification of an existing cell, not a new way
to fill empty cells. Locked cells stay locked. Do not write Jev
confidence as similarity.

## Value extraction

Price, notice period, renewal dates, and liability caps may be extracted
from the already chosen clause in a later iteration. v1 must keep showing
the clause verbatim. Extracted values belong on the version, with
provenance back to the TextUnit, not as a replacement for the cell text.

## Promotion of labels

Human verification labels can later be *offered* as SSR pool candidates.
Promotion is an explicit operator action. Approve/reject in v1 never
activates an anchor.
