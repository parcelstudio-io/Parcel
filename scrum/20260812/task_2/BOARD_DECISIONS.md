# Board decisions — tranche 1 (Fable, 2026-08-12)

## D-1 — W0-A §2 ownership collision: RULED, carrier-type authority

W0-A's stop-and-report (W0A_STATUS.md §2) found that "remove string inference
entirely" is not literally achievable inside W0-A's OWNS:
`navigation/reactive_safety.py:429-445` is a live consumer of `evidence_origin`
and the only producer of SCAN evidence, and `navigation/**` is MUST-NOT-TOUCH.

**Ruling: accept W0-A's recommended resolution.** Authority moves to the
carrier type — `SimObservation` is by definition the simulator contract, so
every sample stamped through it is `SIMULATION`; the string survives only as a
required non-empty fixture label; **no string ever reaches `PHYSICAL`**.
`reactive_safety.py` stays untouched this tranche; the symbol and signature it
consumes are preserved. This satisfies the card's intent (typed provenance, no
string-derived physical authority) without an OWNS breach. Migrating
`reactive_safety.py` itself to the typed carrier is enumerated for the W0-F/W1
follow-up, not this tranche.

## D-2 — W0-A gate-9 gap: IN SCOPE

W0A_STATUS.md §3's finding that `DEFAULT_REQUIRED_INPUTS[SCAN].sim_fixture_allowed
= True` is reused by the physical branch (`runtime.py:483-487`) — so fixture
geometry is admitted on a physically-commissioned deployment — is folded into
W0-A's gate 9 ("no missing-scan/geometry path can emit physical translation"):
the card now requires a physical-deployment requirements table
(`requirements_requiring_physical_inputs()` or equivalent) on which SCAN's
fixture allowance is false. Simulator behavior stays byte-identical.

## D-3 — the "unknown is strongest authority" amplification: RECORDED

`SimObservation.backend = "unknown"` (backends/base.py:89) and
`RobotMotionState.source = "unknown"` (control/models.py:154) both default into
today's `PHYSICAL_SOURCE_NAMES`. Declaring nothing is currently the strongest
authority on both channels. This is the sharpest instance of P0-2 and becomes a
named seeded-failure case in W0-A's gate table (default-constructed boundary
objects must NEVER satisfy a physical join).

## D-4 — tranche interrupted by a host-level shell outage: DISPOSITION

During execution, every shell invocation on this host began returning exit 1
with empty output, across all sessions including freshly spawned ones
(first symptom: an rsync exit 13, then total process-spawn failure; likeliest
cause: process/resource exhaustion under the day's parallel agent load).
Consequences and dispositions:

- **P-1: COMPLETE** except two deferred checks (`git diff --check`, spike
  suite) — to be discharged by the tranche audit once the shell returns.
- **W0-A: STOPPED CLEAN** (no source edits; design handover in
  W0A_STATUS.md §3 is implementation-ready). Re-dispatch with D-1/D-2/D-3
  folded in, first act = ci_gate baseline + AF-2 before-digests.
- **S-1 / W0-B:** disposition per their own stop-reports (pending at time of
  writing).
- No card may close on unexecuted gates; nothing in this outage relaxes
  board rule 1.

## D-5 — W0-A's declared OWNS deviation: RATIFIED

`src/parcel_robot/evidence_origin.py` (new root-level stdlib-only leaf module)
is ratified as W0-A's. The measured constraint was real: placing
`EvidenceOrigin` in `core/input_health.py` dragged `brain`/`instructnav` into
`control/`'s import graph and broke W0-B's leaf invariant — caught only by
W0-A's differential full-suite run. Condition of ratification (audit finding):
the module gains a **leaf-ness pin test** (AST import walk, RM-1's
`test_place_graph_imports_no_onnx_torch_or_navigation` is the precedent) so
the leaf property cannot rot silently.
