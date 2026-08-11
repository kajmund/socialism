# Simulation engine layers

Developer guide for decoupling Opinionssimulator from **camel-oasis 0.2.5** / **CAMEL** internals. Operator docs are unchanged — this page is for builders upgrading dependencies or extending the simulation stack.

Verified against `backend/app/services/oasis_*.py`, `backend/app/services/simulation/`, and smoke tests under `backend/tests/smoke/`.

## Goal

Keep **camel-oasis as the only simulation backend** (no alternate engine protocol), but route all contact with undocumented upstream internals through our own adapter modules. Public camel-oasis APIs (`ActionType`, `ManualAction`, `LLMAction`, `env.step`, graph generators) stay at the boundary.

## Layer map

```text
simulate_run() / jobs                    ← product orchestration (stable)
    └── run_oasis_simulation()           ← tick loop, measurements
            ├── simulation/action_catalog.py     ← Fas B ✓
            ├── simulation/llm_runtime.py        ← Fas A+D ✓
            ├── simulation/agent_tool_policy.py  ← Fas D ✓
            ├── simulation/artifact/               ← Fas C (planned)
            ├── simulation/platforms/              ← Fas E (planned)
            └── oasis_swedish.py                   ← Swedish env prompts (DB-driven, keep)
```

## What is public vs internal in camel-oasis

| Surface | Examples | Our approach |
| ------- | -------- | -------------- |
| **Public orchestration** | `generate_*_agent_graph`, `oasis.make`, `ActionType`, `env.step` | Call directly from adapter |
| **CAMEL / OASIS internals** | `ChatAgent._record_tool_calling`, `SocialAgent._internal_tools`, `SocialEnvironment.get_*_env` | Only via adapter modules; per-run patch restore (Fas A) |
| **Implicit SQLite contract** | `post`, `comment`, `trace`, `user`, … | Typed reader + schema version pin (Fas C) |

There are **no documented extension hooks** for LLM tool recording or per-round tool disable. Comment gating and DeepSeek reasoning require touching private APIs until upstream adds alternatives.

## Phased rollout

| Phase | Scope | Status |
| ----- | ----- | ------ |
| **B** | `simulation/action_catalog.py` — ActionType names, trace strings, engagement classes, social vs external tools | Done |
| **A + D** | Unified LLM runtime (DeepSeek + tool trace) + `CamelCommentToolPolicy`; per-run `camel_llm_runtime()` with refcount restore | Done |
| **C** | `simulation/artifact/` — all `simulation.db` SQL behind typed reader | Planned |
| **E** | `PlatformDriver` (Twitter/Reddit), MBTI fix, optional Reddit smoke | Planned |
| **F** | Stratified sampling by district + lean_key | Deferred (separate small task) |

### Fas B — action catalog

**Module:** `backend/app/services/simulation/action_catalog.py`

- `OASIS_ACTION_SPECS` — ordered list of `OasisActionSpec` (enum name, trace name, platform flags, engagement kind).
- `population_action_names()` — replaces duplicated tuples in `oasis_run.py`.
- `is_social_tool()` / `is_external_tool()` — replaces `_SOCIAL_TOOL_NAMES` in `oasis_tool_trace.py`.
- `passive_trace_actions()` etc. — replaces hardcoded frozensets in `oasis_engagement.py`.
- `validate_action_rules_cover_population()` — optional check that DB prompt `oasis.agents.action_rules` mentions population trace names.

**When adding a new OASIS action:**

1. Add one `OasisActionSpec` row (platform + engagement flags).
2. Update prompt catalog text (`oasis.agents.action_rules` or related keys).
3. Run `uv run pytest tests/test_action_catalog.py tests/test_oasis_actions_readback.py`.
4. Re-run smoke if behaviour changes: `uv run pytest -m smoke` (requires `uv sync --extra oasis` + real `DEEPSEEK_API_KEY`).

### Fas A + D — LLM runtime + comment tool policy

- **`simulation/llm_runtime.py`** — `camel_llm_runtime()` context manager applies combined DeepSeek reasoning + external-tool trace patches; reference counting supports concurrent A/B variants; restores CAMEL originals when the last scope exits.
- **`simulation/agent_tool_policy.py`** — `CamelCommentToolPolicy` gates `create_comment` via `_internal_tools`; tick loop uses the policy instead of direct CAMEL access.
- **`oasis_deepseek_reasoning.py`** — thin backward-compatible re-export shim (deprecated `apply_deepseek_reasoning_patch()` context manager).
- **`oasis_tool_trace.py`** — trace buffer ContextVars only; patching moved to `llm_runtime`.

**Patch order (encoded in llm_runtime):** DeepSeek `_record_tool_calling` replacement → external-tool trace append on the same hook.

### Fas C — artifact store

- Move `_read_oasis_results`, engagement mid-run SQL, and follower/follows reads into `simulation/artifact/reader.py`.
- Pin `SCHEMA_VERSION` to camel-oasis release; fail loud on missing tables/columns.
- Smoke harness asserts against reader models.

### Fas E — platform drivers

- Extract Twitter vs Reddit branching from `run_oasis_simulation()` into `simulation/platforms/`.
- Fix hardcoded Reddit `"mbti": "ISFJ"` in profile JSON (derive from persona or omit if optional).
- Add optional `@pytest.mark.smoke` Reddit variant.

## camel-oasis upgrade checklist

Use this after bumping the `oasis` extra in `pyproject.toml` or when simulation behaviour regresses.

### Before merge

- [ ] Read upstream changelog / diff for `SocialEnvironment`, `ChatAgent`, `SocialAgent`, SQLite schema.
- [ ] `uv sync --extra oasis` in a clean env; note resolved `camel-oasis` version.

### Automated (no API keys)

```bash
cd backend
uv run pytest tests/test_action_catalog.py \
  tests/test_oasis_actions_readback.py \
  tests/test_oasis_engagement.py \
  tests/test_oasis_swedish.py \
  tests/test_oasis_tool_trace.py \
  tests/test_llm_runtime.py \
  tests/test_agent_tool_policy.py \
  tests/test_oasis_deepseek_reasoning.py
```

### Manual smoke (live engine)

```bash
cd backend
uv sync --extra oasis
uv run pytest -m smoke -v
# or: uv run python scripts/run_simulation_smoke.py
```

Requires real `DEEPSEEK_API_KEY`. Asserts: attempt saved, 2 ticks, posts + trace + histogram, no patch crash.

### Adapter-specific checks

| Layer | What to verify |
| ----- | -------------- |
| **Action catalog** | `ActionType` enum still matches our `enum_name` strings; trace.action strings unchanged |
| **LLM runtime (A+D)** | DeepSeek tool loops still carry `reasoning_content`; external tool trace still records; patches restore after run |
| **Tool policy (D)** | Comment gating still works (`create_comment` removed until engagement) |
| **Swedish env** | Feed templates render; follower/follow counts SQL columns still exist |
| **Artifact reader (C)** | All tables in `_read_oasis_results` still present; column names unchanged |
| **Platform (E)** | Twitter stock path + Reddit custom `Platform` still construct; profile CSV/JSON formats accepted |

### After upgrade

- [ ] Run one real körning in admin UI (Twitter, ≥5 personas, 2 ticks, 1 injection).
- [ ] Inspect variant `trace`, `action_histogram`, engagement sampling in results.
- [ ] If schema changed, bump `SCHEMA_VERSION` in artifact module (Fas C) and adjust reader queries.

## Related docs

- [runs-interviews-and-quality.md](runs-interviews-and-quality.md) — tick interviews, branches, quality warnings
- [backend-setup.md](backend-setup.md) — install, smoke harness, benchmark CLI
- [backend/AGENTS.md](../../backend/AGENTS.md) — domain summary for simulation jobs

## Anti-patterns

- **Do not** add new action name lists outside `action_catalog.py`.
- **Do not** add new raw SQL against `simulation.db` outside the artifact module (once Fas C lands).
- **Do not** add process-global monkeypatches without per-run restore (target state after Fas A).
- **Do not** implement fallback simulation engines or silent degradation — fail loud per root [AGENTS.md](../../AGENTS.md).
