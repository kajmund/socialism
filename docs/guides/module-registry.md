# Module registry

Product modules (`dd`, `politik`, later a third) declare themselves in
`backend/app/modules/registry.py`. Shared orchestration (`jobs.py`, Spinndoktor,
panel engine) looks up the registry — it does not `if mode == "dd" else politik`.

## Report.mode → module

`Report.mode` is a pipeline discriminator (`quick` / `full` / `dd`), not a module
id. Each `ModuleManifest` lists the modes it owns in `report_modes`:

| Module            | `report_modes`     |
| ----------------- | ------------------ |
| politik           | `quick`, `full`    |
| dd                | `dd`               |
| expertgranskning  | `expertgranskning` |
| rattsunderlag     | `rattsunderlag`    |

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
5. Seed expert profiles by `(customer_id, key)` (`ensure_expert_profile_defaults`) so an existing expert for that kund gains the new module instead of duplicating rows. Startup and `create_kund` seed catalog defaults per kund.
6. Register `prompt_defaults_provider` for module-owned prompt keys. Shared keys are listed by both `dd` and `politik`; `ensure_prompt_field_defaults` attaches the second module instead of duplicating the row. Runtime loads `require_active_prompts(session, customer_id=…, module=…, language=…)`.
7. Spinndoktor is catalog key `spinndoctor` (modules `dd` + `politik` + `expertgranskning`). Identity uses `panel.expert.system`. Report context and DD panel brief are **separate** messages. `spinndoctor.system` / `.tools` / `.widgets` stay as report-chat policy; `panel.dd.moderator.system` is DD moderator policy on top of the same catalog row.

## Deliberation methods (Fas 3+4)

Two complete methods, not a composable raise-hand strategy:

| Method               | First protocol     | Output                          |
| -------------------- | ------------------ | ------------------------------- |
| `generic_panel`      | `generic_panel`    | `PanelResult` (claims empty)    |
| `structured_scoring` | `dd_panel` | `PanelResult` envelope; DD reports adapt to `DdPanelResult` |

`PROTOCOL_METHODS["dd_panel"]` is `structured_scoring`. The dual-run against `dd_engine.py` is in git history; that file is gone.

## Spinndoktor catalog (Fas 5)

Identity is `PanelExpertProfile` key `spinndoctor` (seeded onto `dd` and `politik`), rendered with `panel.expert.system`.

- Report chat sends two system messages: catalog identity plus policy (`spinndoctor.system`, `.tools`, `.widgets`), then the Fas 2 context block.
- DD panel moderator uses the same catalog row plus policy (`panel.dd.moderator.system`), then the panel brief as a **separate** system message. Phase prompts (`opening` / `sub_question` / `no_answer` / `summary`) stay as user turns.

## Prompt catalog (Fas 1+3)

`prompt_fields` is the key catalog (unique `key`, JSON `modules`). `prompt_overrides` is sparse `(customer_id, prompt_field_id, language)` text. Seed via `prompt_defaults_provider` on each manifest — insert missing keys, attach extra modules, never overwrite existing text. Runtime loads catalog defaults plus that customer's overrides (`require_active_prompts`). `Configuration.prompts` is unused.
