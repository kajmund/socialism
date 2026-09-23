# Jev shadow review scheduling

In `shadow` mode, Jev screening/assessment and the authoritative LLM review execute concurrently. The same scheduling applies to the global completeness reviewer. The LLM result remains authoritative; Jev is still recorded for comparison and cannot skip that review in shadow mode.

Previously the authoritative review started only after the Jev request completed. The new ordering removes that serial dependency. Overall wall time still includes the slower branch: it is approximately the maximum of the Jev path and the LLM path, rather than their sum. This is a scheduling property, not a measured production latency claim. Enabling item screening can still make the Jev branch expensive.

Active mode retains sequential gating so a calibrated positive Jev decision can avoid starting the LLM request. Disabled and programmatically decidable paths retain their existing behavior.

A shared helper awaits both shadow branches. If the authoritative review fails or the caller cancels, remaining tasks are cancelled and awaited before the error propagates. Latency recorded for the LLM measures that branch itself, not time waiting for Jev.

Regression tests use synchronization events to prove both branches start before Jev completes, for assessment and completeness. They also verify authoritative error propagation and cancellation cleanup. No network timing or sleeps are required to establish concurrency.
