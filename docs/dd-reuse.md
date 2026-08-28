# DD reuse — bolag GUI on politics admin shell

Reuse the politics admin visual system and job/realtime patterns for bolag (DD) workflows. Phases are incremental on one feature branch/PR.

## Phase status

| Phase | Status | Notes |
| ----- | ------ | ----- |
| **A** | Done | Schema: `Persona.kind`, nullable age, population/job/report `kind` + `customer_id` |
| **B** | Done | Expert personas via composer; bolag `/bolag/experter`; default seed |
| **C** | Done | Expert panels via Population Builder; `expert_panel_id` on campaigns; `DdCampaignPanelSection` picker |
| **D** | **Closed — skipped** | No separate configure page. A DD panel session has exactly two params (candidate + expert panel), both chosen on the campaign editor before **Kör**. `DdCampaignPanelSection` is the correct home — a dedicated page would only duplicate the campaign editor. |
| **E** | Done | Live panel view: `PanelBroadcastRegistry`, `/ws/panels`, `usePanelWatchSocket`, `PanelLiveFeedPanel` on campaign cards |
| **F** | Done | Parametrized `AdminShell` / `BolagShell` |
| **G** | Pending | Scoped Jobs/Reports for bolag |
| **H** | Pending | Full bolag nav |

## FAS E — live panel watch

Mirrors run live feed (`RunBroadcastRegistry` / `/ws/runs` / `useRunWatchSocket`):

- Room key: `session_id`
- Hello: `{ type: "hello", scope: "panel_watch", session_id }`
- Events: `panel.replay`, `turn.started`, `turn.completed`, `panel.finished`
- UI: `PanelLiveFeedPanel` under each selected candidate card while a panel session exists

See [panel-engine.md](./panel-engine.md) for protocol and persistence details.
