# SWE consumer runbook (Socialism)

Socialism **consumes** the Socialism Workflow Engine (SWE) from the standalone
repository [`kajmund/swe`](https://github.com/kajmund/swe). The generic engine
no longer lives in this tree. This guide is the developer-facing map of pins,
builds, ownership, and common pitfalls after PRs
[#458](https://github.com/kajmund/socialism/pull/458)–[#460](https://github.com/kajmund/socialism/pull/460).

Historical extraction notes remain under
[`docs/swe-standalone/`](../swe-standalone/README.md) (investigation record).
Engine contracts and SWD semantics live in
[`docs/specs/swe-swd-1.0.md`](../specs/swe-swd-1.0.md),
[`swe-runtime.md`](../specs/swe-runtime.md),
[`swe-overgraph.md`](../specs/swe-overgraph.md), and
[`swe-provider.md`](../specs/swe-provider.md).

## Intent

| Owns | Location |
| --- | --- |
| SWD 1.0 schema, Rust kernel, `swe_native` PyO3 module, Python host (`import swe`), journal/budget contracts, package + mutation gates | [`kajmund/swe`](https://github.com/kajmund/swe) |
| Research wave bridge, host context, OverGraph durable store adapter, exact Jev cache, product handlers | This repo (`backend/app/services/research/swe_bridge.py`, `swe_host/`, `overgraph/workflows.py`, `overgraph/jev_cache.py`) |
| Gym / Sweycoin experiments that exercise the pinned engine | `crates/swe-gym/` (git deps on the same tag) |

SWE is the **only** research execution loop. There is no dual runner or
“if SWE unavailable, fall back” path.

## How Socialism pins SWE

Two surfaces must stay on the **same release tag**:

| Surface | Where | Current pin |
| --- | --- | --- |
| Python distribution `swe-engine` (import package `swe`) | `backend/pyproject.toml` → `tool.uv.sources.swe-engine` | git `https://github.com/kajmund/swe`, tag `v0.1.0`, subdirectory `python` |
| Native extension `swe_native` | Root `Makefile` `SWE_TAG` / `SWE_REPOSITORY` | same tag; source cloned under `.cache/swe` (gitignored) |
| Gym crates | `crates/swe-gym/Cargo.toml` | `swe-native` / `swe-budget` git deps at the same tag |

`uv sync` installs the Python package. It does **not** compile `swe_native`.
Local and CI builds of the extension always come from the pinned tag checkout,
not from a copy under `crates/` in this repository.

## Local setup

Prerequisites: Rust **1.83**, Python **3.12+**, [`uv`](https://docs.astral.sh/uv/),
network access to GitHub for the public `kajmund/swe` tag.

```bash
# Install backend deps (pulls swe-engine==0.1.0 from the pinned tag)
cd backend && uv sync

# Build swe_native from the same tag into the backend venv
make swe-native

# Consumer contracts only (dependency pin + adapters + research wiring)
make test-swe
```

`make swe-native` clones/fetches into `.cache/swe`, checks out `SWE_TAG`,
asserts HEAD matches the tag tip, then runs
`maturin develop --manifest-path …/crates/swe-native/Cargo.toml` inside
`backend/`. Override the cache path with `SWE_SOURCE=/path make swe-native`
when needed.

`make test-backend` depends on `swe-native`, so a normal `make test` also
rebuilds the extension when the Makefile target runs.

## What Socialism may and may not change

**Do**

- Extend product adapters and handlers in this repo.
- Bump the pin by changing `SWE_TAG` in the Makefile **and** the
  `swe-engine` uv source tag (and swe-gym git tags) together, then refresh
  `backend/uv.lock`.
- Run engine-side package / contract / mutation gates in `kajmund/swe`.

**Do not**

- Re-add `backend/app/swe`, `python/swe`, or `crates/swe-native` to this repo.
- Vendor a local engine checkout as a path dependency.
- Teach the engine about OverGraph catalogs, prompt catalogs, or research
  domain types — that belongs in Socialism host adapters.

CI rejects a local engine copy via
`backend/tests/test_swe_dependency_contract.py` and the `swe_runtime` job
(see [ci.md](ci.md)).

## Codepaths covered by the consumer contracts

| Test / target | Verifies |
| --- | --- |
| `tests/test_swe_dependency_contract.py` | Installed `swe-engine` revision matches the pyproject tag; a minimal SWD workflow completes through `swe` + `swe_native` |
| `tests/test_swe_provider.py`, `tests/test_swe_persistence.py` | Socialism provider / persistence adapters against the pinned runtime |
| `tests/test_research_swe/test_wiring.py` | Research bridge wiring (`swe_bridge`) |
| `tests/test_sufficiency_experiment_reuse.py` | Opt-in sufficiency experiment reuses `WorkflowRunner` like the bridge |
| `make test-swe` | All of the above with `-m swe_runtime` after `make swe-native` |

Production research still enters through
`execute_attempt_research` → `_run_research_loop` →
`run_research_loop_via_swe` (`app/services/research/swe_bridge.py`). SWE owns
wave scheduling (`map` / `decision`); research keeps planning, need bodies,
evidence, quality, assessment, completeness, and freeze.

## Common pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: swe_native` / `importorskip("swe_native")` skips | Python package installed, extension not built | `make swe-native` (needs Rust 1.83 + maturin via the backend env) |
| Consumer tests fail after editing only `SWE_TAG` or only `pyproject.toml` | Pin skew between Python git dep and native source | Keep Makefile `SWE_TAG`, uv `swe-engine` tag, and swe-gym git tags identical |
| Temptation to path-depend on a local SWE clone for “faster iteration” | Breaks the consumer contract and CI | Develop engine changes in `kajmund/swe`, cut a tag, then bump the pin here |
| Looking for engine sources under `crates/swe-native` in this repo | Removed in #460 | Use `.cache/swe` after `make swe-native`, or clone `kajmund/swe` |
| Assuming `uv sync` alone is enough for research tests marked `swe_runtime` | Extension is a separate build step | Always run `make swe-native` (or `make test-swe`) before those tests |
| Adding a second research loop “just in case” | Violates no-fallback / single execution path | Fix the bridge or the engine; do not restore `loop_control.run_research_loop` |

## Related

- Agent notes: root [`AGENTS.md`](../../AGENTS.md), [`backend/AGENTS.md`](../../backend/AGENTS.md)
- CI job layout: [ci.md](ci.md)
- Backend install / env: [backend-setup.md](backend-setup.md)
- Standalone extraction archive: [`docs/swe-standalone/`](../swe-standalone/README.md)
