# Document tags inventory

Completed before implementation.

| Finding | Value |
|---|---|
| `socialism_has_document_tag_model` | False |
| `openapi_tags_are_unrelated` | True |
| `speaker_user_label_is_unrelated` | True |
| `passage_marks_are_highlights_not_tags` | True |
| `expertgranskning_document_type_is_free_text` | True |
| `reuse_experiment_overgraph` | True |
| `reuse_frozen_doctype_b` | True |
| `do_not_create_parallel_tag_database` | True |
| `tenant_props` | ('tenant_id', 'workspace_id') |
| `jev_fields_stored_raw` | ('confidence', 'probabilities') |
| `citation_path` | TextUnit excerpt must be an exact substring |

Reuse experiment OverGraph Document/Tag nodes.
Reuse frozen `phase2-doctype-run-v1` variant B for
`predicted_type`, confidence, and probabilities.
Do not import `backend/app`.

