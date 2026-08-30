# Guarded test runs — 2026-08-29

All pytest invocations were made through
`~/.cache/parcel-guard/pytest_guard.sh`; the live owner stack on port 8765, the live
simulator socket, and the default persistent memory database were not touched.

## Targeted results

- Acoustic-loop evaluator and regression tests: **15 passed**.
- All acoustic/duplex-related tests: **124 passed in 4.90 s**.
- Duplex transaction v2 product-seam tests: **2 passed in 0.41 s**.
- Task executive plus companion-state authority tests: **63 passed**.
- Companion relationship/dynamic/Realtime prompt contracts: **71 passed in
  0.80 s**. These assert the “ongoing companion friend” default and its safety,
  consent, memory, and installed-skill boundaries.
- Current mount-boundary code (gateway peer credentials/protocol, disarmed and
  commissioned compositions, runtime backend lifecycle, control manager,
  Unitree port, generalized motion, affordance planning, and proposal-only
  skill-outcome learning): **474 passed, 4 skipped in 620.47 s**. The long
  buffered middle section completed; it was not a deadlock. This remains
  desktop/injected-binding evidence, not a real SDK2/Go2 or Orin result.
- Frozen live-planner boundary replay: matched with zero mismatches; the stored
  PlanIR remained accepted with plan digest
  `8ab455dfd03a9316a0007987abcccc1655129839e40876025186ac41a4f248fc`.
  This revalidates a historical one-case record and performs zero model calls or
  navigation episodes.
- SOS-1 stop-only principal: **27 focused tests passed**; its broader guarded
  gateway selection passed **273 with 4 skips**. This is source/fake-gateway
  software evidence, not a real STOP input or hardware E-stop test.
- Frozen DMC-4 journal/bridge: **28 focused tests passed**; its broader guarded
  transaction selection passed **307 with 4 skips**. This proves the
  source-level journal-only transaction. A later additive hardening step wired
  a process-local observer into normal runtime and passed a focused **26-test**
  selection; neither result wires a provider, audio, a live session key/epoch,
  a persistent cursor, or separate-child resume lineage.

## Final hardening shards

These six disjoint, risk-oriented selections were rerun after the August 29
hardening changes. They are software regressions on this desktop with injected,
mocked, or simulated boundaries; they are not Go2/Orin or physical-safety
qualification.

- Mount boundary and motion authority: **659 passed, 4 skipped in 37.02 s**.
- DMC-4 and adjacent runtime semantics: **159 passed in 7.33 s** (2 warnings).
- Conversation and prompt truthfulness: **419 passed in 5.45 s**.
- Duplex and acoustic software path: **264 passed, 1 skipped in 6.97 s**.
- Dynamic-person and false-stall navigation: **279 passed, 7 skipped in
  13.10 s** (2 warnings).
- Packaging, Orin portability, assets, and physical-profile assertions:
  **485 passed in 28.94 s** (1 warning).

The repository-wide commit gate is reported separately when complete; these
shard totals must not be summed into a unique-test count because files overlap.

## Broad selected evaluation suite

A selected 45-file conversation, Realtime, preemption/resume, voice-navigation,
NAV_INSTRUCT, dynamic, and social-navigation run initially reported 1,570 passed,
37 failed, and one expected failure in 754.64 s.  Thirty-six failures were traced to
cross-test accumulation in the explicitly supplied SQLite path, not product logic.
The remaining navigation failure was a one-run `semantic_target_unreachable` result.

The relevant failures were rerun with `PARCEL_MEMORY_PATH=:memory:`: **356 passed and
one failed**.  That remaining case was the explicit persistence-migration test, for
which the in-memory override intentionally prevents the temporary file migration.
With the override unset, the migration test passed.  The transient navigation case
also passed alone in 67.72 s.

This clean rerun removes the database-contamination failures but does not erase the
transient navigation stall observation.  Capability conclusions therefore use the
fresh standalone evaluation artifacts in this directory rather than pytest pass
counts.
