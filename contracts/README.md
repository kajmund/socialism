# Frozen contracts, v1

These files are the **behavioural surface** the extraction promises not to change
without a version bump. They are not documentation of the implementation; they
are inputs the tests execute.

| File | Contract | What it pins |
| --- | --- | --- |
| `swd-v1-workflow.json` | SWD 1.0 | A complete workflow document: task, expression and provider decisions, map, fork/join, end statuses |
| `journal-v1-header.json` | Journal header v1 | `schema_version`, run identity, definition hash, contract version, dependency versions |
| `journal-v1-events.json` | Journal events v1 | Every event kind, including an unconfirmed external charge |
| `MANIFEST.sha256` | Structural | SHA-256 of each file above |

## Two gates, not one

A hash proves the **bytes** did not change. It does not prove the **behaviour**
did not change, and it cannot tell an intended change from an accidental one. The
contract gate therefore has two halves, both in `crates/swe-reference/tests/contracts.rs`:

1. **Structural** — every file matches `MANIFEST.sha256`, and the directory
   contains exactly the listed files (no unlisted fixture can appear).
2. **Semantic** — the fixtures are *executed*: the SWD document is compiled and
   must hash to the definition hash in the journal header; every journal event
   decodes and re-encodes identically; `NeedMore` repeats end the loop;
   duplicated need statuses and `AMBIGUOUS` evidence are typed refusals; journal
   recovery is decided per delivery class; wrong schema, contract and dependency
   versions are refused **and name the version**.

## Changing a contract

Both halves must change together, deliberately:

1. Change the contract and add a **migration test or a documented breaking
   decision** (a short note in `docs/swe-standalone/` saying what breaks and why).
2. Bump the relevant version: `JOURNAL_SCHEMA_VERSION`, `CONTRACT_VERSION`, or
   the SWD contract's own version.
3. Regenerate the fixtures:
   `cargo run -p swe-reference --example emit_contracts`
4. Update `MANIFEST.sha256` in the **same commit**:
   `cd contracts && shasum -a 256 *.json > MANIFEST.sha256`

A PR that changes a fixture's *shape* without its contract version bump fails
CI, and so does a changed manifest; a PR that bumps the version without a migration test or a documented breaking
decision is rejected in review. That is the whole mechanism — no silent drift,
and no ceremony when nothing changes.

## What the semantic tests do *not* cover

They cover what the code can express in Rust. Python-side wire behaviour
(adapter readers, differential tests) is covered by the standalone harness in
`python/tests/`. Neither replaces the other: the fixtures are the shared
specification both sides are checked against.
