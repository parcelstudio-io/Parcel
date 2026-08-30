# Guarded test runs — 2026-08-29

All pytest invocations were made through
`~/.cache/parcel-guard/pytest_guard.sh`; the live owner stack on port 8765, the live
simulator socket, and the default persistent memory database were not touched.

## Targeted results

- Acoustic-loop evaluator and regression tests: **15 passed**.
- All acoustic/duplex-related tests: **124 passed in 4.90 s**.
- Additive PortAudio drain-abort and post-open playback-clock selection:
  **86 passed with 2 expected warnings**. This is source regression evidence;
  the later v1 audit keeps mounted/audio capability red.
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

## Post-Sol-Ultra bounded regressions — 2026-08-30

These overlapping guarded selections close source defects found by the fresh
read-only review; they do not change the hardware evidence tier:

- process-local revision exception atomicity, including deferred checkpoint and
  after-step rollback, plus navigation recovery failure mapping: **70 passed**;
- deployment graph/profile and checkout-provenance direct selection:
  **98 passed**; broader related selection: **145 passed**;
- complete available Model-B lineage and drain-time expiry: **9 passed**;
- committed terminal-geometry identity on the one-shot pose retry:
  **14 passed**; and
- mandatory gateway `--disarmed` assertion: **8 passed, 1 skipped**.
- combined changed-surface integration selection: **125 passed, 4 skipped**.

The first revision transaction compensation was not crash-durable, distributed,
or isolated from concurrent proposal publication/arbitration. A second
independent review found that gap, plus service lifecycle/environment precedence
and valid Model-B lifecycle defects. The postfix panels passed **33** service
tests, **14** Model-B/oracle tests, and **14** revision/concurrency tests. One
combined selection spanning those surfaces passed **91/91**. Revision commit is
now thread-isolated inside one process, but remains non-crash-durable and
non-distributed; checkout provenance is start/end identity rather than atomic
execution attestation; and the systemd graph has not run on an Orin.

A third independent read-only audit then found four residuals: the older motion-
seam parity test did not understand the late environment wrapper, target
activation was not fail-loud for core services, broader valid Model-B histories
still false-latched, and shared sinks could be acquired in opposite executive
registration orders. The exact guarded remediation panel passed **19/19**.
Shared sinks now use a process-wide object-identity lock order; this still does
not provide crash or distributed durability.

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

## August 30 extended nightly and remediation

The guarded 6,785.5-second extended nightly completed. Its default selection
passed 11,262 with 23 skips and 5 expected failures, and mutation testing killed
7/7 injected defects. The gate remained hard red because all six pose-drift arms
missed their frozen success floors. The initial slow selection returned 4 failed,
68 passed, 8 skipped, 3 expected failures, 1 unexpected pass, and 3 wheel-fixture
setup errors.

After evidence-bounded fixes to retired-literal ownership, held-out-name hygiene,
Python-3.14 wheel installation, and one-shot alternate terminal-pose recovery:

- affected focused selection: **152 passed, 4 skipped, 2 warnings in 88.79 s**;
- live `sit next to the lamppost` E2E: **passed twice**, in 79.89 s and 81.74 s;
- post-remediation slow marker selection: **1 failed, 74 passed, 8 skipped,
  11,293 deselected, 3 expected failures, 1 unexpected pass, 2 warnings in
  2,007.26 s**.

The sole slow failure is the unchanged undeclared-bystander deadlock pin:
`veto_fraction=0.875` versus `>=0.9`. The trace is deterministic, remains a
deadlock, and has zero collisions; the evaluator was not weakened after seeing
the result. The complete audit is
[`../NIGHTLY_REMEDIATION_AUDIT.md`](../NIGHTLY_REMEDIATION_AUDIT.md).

The pre-postfix guarded commit tier on the then-current documentation tree passed every hard
row in **269.3 s**. Coverage collected 11,380 tests: 11,293 commit and 87 slow,
with no orphan or overlap. Its default phase returned 11,253 parallel passes,
22 skips, and 5 expected failures, followed by 12 serial passes and 1 skip. The
Ruff ratchet remained 72 baseline / 72 current / 0 new. The stopping-envelope
row remains report-only and explicitly unmeasured.

After the independent postfix work, the guarded commit tier again passed every
hard row in **274.0 s**. Coverage collected **11,417 tests: 11,330 commit and 87
slow**, with no orphan or overlap. The default phase returned **11,290 parallel
passes, 22 skips, and 5 expected failures**, followed by **12 serial passes and
1 skip**. Ruff remained 72 baseline / 72 current / 0 new; release parity checked
106 assets; the stopping envelope remained explicitly unmeasured. This run's
start/finish HEAD and index matched, but its checkout content identity did not:
concurrent Claude work wrote the shared root during the gate. All hard rows are
green, but this particular report is not an unchanged-checkout attestation; a
quiet-tree repeat is required for that narrower provenance claim.

The quiet repeat then passed every hard row in **280.3 s** with the same
**11,417 = 11,330 non-slow + 87 slow** partition, default-suite results, and
72/72/0 Ruff ratchet. Its checkout identity was byte-identical at start and
finish (`f8518f4283f8…`), with HEAD and the complete index unchanged. This is
start/end Git-visible content identity—not execution, environment, ignored-file,
or hardware attestation—and the extended nightly result remains red.
