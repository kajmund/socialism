# Search generations for Tabular Review snapshots

Status: ticket 46 prerequisite design. No production change.

## Why

A warm Top-K snapshot may only be reused when the searchable units and the
authoritative anchor membership are unchanged. Hashing 2 377 TextUnits on every
warm request would erase C's advantage. Use two atomic generation counters.

```text
SearchableCorpus
  scope_key
  generation = 184

AnchorSet
  id, version
  membership_generation = 42
```

A snapshot stores both generations. Validation is two cheap reads, not a corpus
scan.

## Atomicity

The generation increment must be committed in the same atomic write as the
change it represents:

- TextUnit insert/update/delete/partial re-ingest or changed segmentation →
  `SearchableCorpus.generation += 1`.
- Anchor promotion/revocation or membership change →
  `AnchorSet.membership_generation += 1`.

`Catalog.graph_patch` already exposes one locked engine write for a batch of
nodes/edges. The ingest and anchor mutation paths must put the generation node
and the changed node(s) in the same patch. If a path cannot do that yet, it
must not advance the generation separately: a separate counter write would
leave a window where new data is searchable under the old generation.

## Double check

```text
read generations G1
compute Top-K
read generations G2
if G1 != G2:
    discard current result; retry once (bounded)
else:
    store immutable snapshot with G1
```

A pure cache hit also validates G1 against current generations. A technical
failure during validation means recompute, never stale reuse. If the retry also
races, store the result as historical, not current.

## Snapshot

- immutable Top-K + scores + source references + fingerprint + generations
- `computed_at`
- review cell points at snapshot, keeps approval/lock/history separate
- locked cell is preserved but marked `Historiskt resultat – underlaget har
  ändrats` when its snapshot generations no longer match

## Validation cost

Measure two generation reads separately from scoring. Target is tens of
milliseconds, not 14 ms; correctness wins. Do not hash the whole unit set on the
normal warm path.

## Sequence

1. ticket 46: atomic generation writes + read API.
2. ticket 45: snapshot + double check + C/D invalidation parity.
3. UI marking, workers/restart tests, then adoption decision.
