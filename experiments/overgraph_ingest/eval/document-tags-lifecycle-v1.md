# Document-tag lifecycle

Design review after the 16-document tag run. No Jev.
A stays the cheap ingest candidate. B stays an experimental
alternative for more semantic classes. Automatic tags are
proposals, not legal facts.

## Two meanings, one Tag node

| Kind | Meaning | Source |
|---|---|---|
| `extracted_property` | Typed document property | Required to present as source-verified |
| `user_label` | Organizational label | Never required |

## Rules

- Same Tag nodes. Kind distinguishes meaning.
- Identity is tenant, workspace, document, class, and value.
- Origin is an attribute, not the identity.
- User labels start verified and never require a source.
- Extracted tags stay proposals until a user reviews them.
- Rejected values stay rejected on re-ingest.
- Correcting a value rejects the old value and locks the new one.
- Unreviewed automatic tags not re-proposed are withdrawn.
- User decisions survive re-ingest, reclassify, and document delete.
- Delete hides the document from filters and keeps tag tombstones.
- Restore plus ingest of the same document id reapplies those decisions.
- Socialism must key decisions on a stable workspace document id.
- Automatic extraction should read effective_type, not predicted_type.

## Proof

| Check | Value |
|---|---|
| `user_label_kind` | user_label |
| `user_label_source_verified` | False |
| `corrected_old_rejected` | True |
| `corrected_new_locked` | True |
| `probationary_stays_rejected` | True |
| `notice_withdrawn` | True |
| `unvalidated_extracted_not_source_verified` | True |
| `deleted_hidden_from_filter` | True |
| `restored_effective_type_locked` | True |
| `user_label_survives_delete` | True |
| `permanent_survives_reingest` | True |
| `kinds_share_tag_nodes` | True |
| `automatic_tags_are_proposals` | True |

## What this is not

- Not a new tag-quality experiment.
- Not production ingest.
- Not a change to Tabular `answer_cell`.
- Not a new Jev prompt for harder legal properties.
