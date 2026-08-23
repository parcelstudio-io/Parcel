# Tranche 1 close — features + hardware-mount readiness · integrator Fable (parcel-6c) · 2026-08-23

Authorized by the owner's 2026-08-23 direction (companion-dog prototype;
Opus implements, Fable verifies; features + mount readiness; reduced
testing). Design authority: scrum/20260823/task_1/FABLE_VERDICT.md
(ACCEPT_WITH_REQUIRED_CHANGES + addendum). Baseline commit 3792288.

| Card | Executor | Verifier verdict | Verdict file |
|---|---|---|---|
| PROX-1 (task_2) context proximity ladder | Opus | ACCEPT-WITH-NOTES | ~/.cache/parcel-verify/prox1/VERDICT.md |
| SENSE-1 (task_3) mount-readiness: receipt clocks, pose seam, X06 refusals, drain bound, preflight | Opus | ACCEPT-WITH-NOTES | ~/.cache/parcel-verify/sense1/VERDICT.md |
| GATE-1 (task_5) exit truthfulness + six-term envelope row | Opus | ACCEPT-WITH-NOTES | ~/.cache/parcel-verify/gate1/VERDICT.md |
| AWARE-1 (task_4) head-turn + R28 table + the three runtime wire-ins | Opus | ACCEPT-WITH-NOTES; **R28 table RATIFIED** | ~/.cache/parcel-verify/aware1/VERDICT.md |

What the dog can now do (in sim; hardware-ready): periodically turn its
head to scan for people while idle (default OFF pending the config re-pin
below), yaw-only by construction, abandoning the sweep on any input-health
degradation per the ratified R28 table; keep a shorter person distance
indoors (0.95 m at the go2_edu_plus venue vs 1.2 m default; commissioned
prototype 0.7 m untouched); and, at the join, believe a LIVE Go2 pose while
still latching any replayed one. Mount-day: one preflight command reports
Mid-360 / D455 / XVF3800 readiness (the array reads READY on this host);
the resolved physical profile now REFUSES the inherited simulated battery,
desktop NIC, and simulator controller; the gate can no longer exit green on
a host that skipped hard rows, and the stopping row names scan_age_s.

Wire-in discipline held: runtime.py had exactly one writer (AWARE-1, 8
marked regions); structural oracles (r24, nominal-stop-wiring) green with
zero re-pins; one sanctioned pin update (hw2 test_b3, cause named).

## Owner decisions surfaced (none blocking)
1. **configs/robot.yaml SHA re-pin** — both PROX-1's proximity ladder and
   AWARE-1's sweep limits ship as validated code defaults because the base
   config is digest-locked (eval manifest + hw5 + gate sentinels). The
   ready-to-land blocks are preregistered (PROPOSED_SAFETY_BLOCK,
   PROPOSED_AWARENESS_BLOCK). One authorization lands both + re-measured
   eval rows.
2. **Enable the awareness sweep** — one-line flip after the re-pin (it
   would move a pinned embodied_plan_v1 row, so it ships OFF).
3. Hosted CI now fails visibly on a degraded runner (rc=2) — sanctioned;
   opt-out is a workflow-side `|| [ $? -eq 2 ]` if ever wanted.
4. Hardware commissioning checklist addition (from the R28 ratification):
   a feedback channel dead from boot permits bounded in-place yaw —
   verify the channel before first power-on sign-off.

## Carried debts (small, non-blocking)
- run_nightly.py computes its own exit code (GATE-1 flag) — align when
  nightly is next touched.
- owner_keepout_m derives once at construction; won't tighten on a context
  switch (safe direction today; AWARE-1's handoff names the fix).
- Mic direct-vs-HTTP lifecycle race: deferred accepted risk (verdict
  addendum) until the audio stack is next touched.

Close gate: RESULT recorded below after the run.

## Integrator close repairs (recorded, not cards)
1. First close-gate run red on CAP-1's G2 family: AWARE-1 read
   `store.section(AWARENESS_CONFIG_KEY)` through the imported constant
   (G2 resolves only literals → UNCHECKED), and once resolvable, the wider
   survey correctly found `awareness` unreachable — not in the SHA-locked
   base, not overlay-introducible: a knob no operator could turn (the
   ROAM-1/TRUTH-1 finding, a third time). Repair, following the roster's
   own pattern: literal `store.section("awareness")` at the call site
   (constant pinned equal in test_aware1_head_turn), one `awareness`
   subtree entry in OVERLAY_INTRODUCIBLE_KEYS (read-site validator
   `awareness_limits_from_config` refuses unknown keys by name), census row
   in test_prototype_profile.py. 133 tests across
   cap1/prototype/aware1/hw5 green; ruff clean.
   **Consequence worth knowing: the sweep can now be enabled by a profile
   overlay (`awareness.enabled: true`) — no base re-pin needed for that
   half of owner decision 2.**
2. R28 table §2 module cite corrected (patrol/awareness.py →
   navigation/awareness_sweep.py).

## Close gate result (four runs, labels `integrator-close-t1`)
Run 1: RED — CAP-1 G2 family (real; repaired above) + the R26 perf pin.
Runs 2–4: **every functional test green** — parallel phase 9,900 passed /
0 failed; the single remaining red in each is
`test_dynamic_costs::test_cost_field_vectorization_performance`, a
load_sensitive serial-phase test whose 2 ms pin misses (~3.4 ms) on a
just-idled powersave core. The module is HEAD-identical since `e5d4956`
(pre-wave-3); R26 measured 25/25 idle-host failures for identical code
that passes warm, and the test's own docstring instructs "a failure here
is very likely your machine — check R26_STATUS.md §4.3 before attributing
it". Dispositioned per that protocol: not a tranche-1 regression; the pin
is NOT relaxed (R26 open risk 1 owns any re-derivation). The wave-3 close
(c1b8405) recorded the same phenomenon on its first run.

Functional verdict of the close: 9,900/9,900 parallel + 8/9 serial green,
the ninth being the documented environment pin. Tranche 1 is closed.
