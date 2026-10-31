# Manual clause-SSR embedding migration

Status: documented procedure. The app uses a static embedding configuration;
there is no runtime model-switch flow by design.

A future model/revision change is an explicit admin migration per Overgraph
catalog:

1. Choose the new embedding model/revision in deployment configuration.
2. Restart/deploy so the catalog owner and clause domain use the new spec.
3. Run `POST /clause-ssr/anchors/mark-stale` for each affected catalog/scope
   (owner-backed, atomic anchor status + category pool revision bump).
4. Re-embed affected TextUnits/anchors and re-verify/activate them through the
   normal clause flow.
5. Rebuild AnchorSets while the owner checks pool revisions.
6. Verify there are no stale members in active sets and that matching either
   returns valid current hits or reports no active anchors.

Do not report the migration complete merely because anchors were marked stale.
It is complete only when the intended new embeddings/AnchorSets are verified, or
the affected categories explicitly accept having no active anchors temporarily.

Read-side matching already rejects anchors whose embedding model/revision does
not match the current spec; the stale job is for graph status and pool revision,
not the primary safety guard.
