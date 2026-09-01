# Module registry

Product modules (`dd`, `politik`, later a third) declare themselves in
`backend/app/modules/registry.py`. Shared orchestration (`jobs.py`, Spinndoktor,
panel engine) looks up the registry — it does not `if mode == "dd" else politik`.

## Report.mode → module

`Report.mode` is a pipeline discriminator (`quick` / `full` / `dd`), not a module
id. Each `ModuleManifest` lists the modes it owns in `report_modes`:

| Module   | `report_modes`     |
| -------- | ------------------ |
| politik  | `quick`, `full`    |
| dd       | `dd`               |

`module_id_for_report_mode(mode)` returns the unique owner. Unknown or colliding
modes raise — there is no fallback to `politik`.

`ReportBinding.generate` is the report job implementation for those modes. Adding
a third module means adding a manifest entry (and a frontend `reportModes` list),
not another branch in `jobs.py`.

## Startup guard

`assert_unique_report_modes()` runs at import. Two modules claiming the same
mode, or `report_modes` without a `ReportBinding`, fail boot.

## Frontend

`frontend/src/modules/*/manifest.ts` mirrors `reportModes`.
`moduleForReport()` looks up that field and throws on an unknown mode.

## Spinndoktor source (Fas 2)

`SpindoctorBinding` has a uniform pair:

- `source_loader(session, report) -> SpindoctorSource`
- `context_builder(source, *, locale, title) -> str`

`build_spindoctor_context` looks up the module via `report_modes`, loads the source, and builds context. It does not branch on `report.mode`. DD payload is `report.dd.json`; politik payload is OASIS bundles.

`POST /reports` resolves `mode` and source type through the registry (`resolve_report_mode`). A third module's `report_modes` / `source_types` are accepted without a new schema literal.

`load_spindoctor_source` remains a compat wrapper that returns `(report, source.bundles)` for MCP/tools (DD: empty list).

A test-only third module lives in `backend/tests/fixture_module.py`. It must not import `app.services.dd`, `spindoctor_dd`, or `spindoctor_politik`. See `tests/test_fixture_module.py`.

## Adding a module (checklist)

1. Backend `ModuleManifest` with `report_modes` + `ReportBinding` (if it produces reports).
2. Frontend manifest with the same `reportModes`.
3. Spinndoktor `source_loader` / `context_builder` — no `if report.mode` in `spindoctor_context.py`.
4. Panel protocol via `DELIBERATION_METHODS` (`generic_panel`, `structured_scoring`), not a new `jobs.py` branch.
5. Seed expert profiles by `key` (`ensure_expert_profile_defaults`) so existing experts gain the new module instead of duplicating rows.
6. Report-chat Spinndoktor is catalog key `spinndoctor` (modules `dd` + `politik`). Identity uses `panel.expert.system`; report context is a **separate** message. `spinndoctor.system.tools` / `.widgets` stay as policy prompts. DD panel moderator is still `panel.dd.moderator.*` (not migrated).

## Deliberation methods (Fas 3+4)

Two complete methods, not a composable raise-hand strategy:

| Method               | First protocol     | Output                          |
| -------------------- | ------------------ | ------------------------------- |
| `generic_panel`      | `generic_panel`    | `PanelResult` (claims empty)    |
| `structured_scoring` | `dd_panel` | `PanelResult` envelope; DD reports adapt to `DdPanelResult` |

`PROTOCOL_METHODS["dd_panel"]` is `structured_scoring`. The dual-run against `dd_engine.py` is in git history; that file is gone.

## Spinndoktor catalog (Fas 5)

Report-chat identity is `PanelExpertProfile` key `spinndoctor` (seeded onto `dd` and `politik`). The chat sends two system messages: catalog identity (`panel.expert.system`) plus policy prompts (`spinndoctor.system`, `.tools`, `.widgets`), then the Fas 2 context block. DD panel moderator stays on `panel.dd.moderator.*`.
