# W1-J status — J-A, J-B, J-C (jerk drift: pure ramp, severity split, ratchet + attributed re-pin)

**Lane:** W1-J (executor: Claude Opus). **Base:** `dd2e857`, working tree carries
a CONCURRENT sibling lane (W1-D15) — see §6 for the isolation proof.
**Record:** `scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` §0, §3, §6 cards J-A/J-B/J-C, §7.
**Not committed.** Nothing was committed by this lane.

## 0. Headline

| Card | Verdict |
|---|---|
| J-A | **CLOSED.** `core/stop_ramp.py` + 12 contract tests, bit-equal to the 60ecea2 emergency hunk. |
| J-B | **CLOSED WITH ONE PRE-REGISTERED MISS (STOP-and-report).** Flag-off byte-identity PROVED on a full 11-scenario bench. Flag-ON jerk **1.0813** vs the **≤1.05** bar → **MISS**. Not tuned, not renegotiated. Every safety criterion of the gate passed bit-identically. Flag stays default OFF; the default-flip decision is the owner's. |
| J-C | **CLOSED.** New hard gate `follow-bench-jerk-ratchet` PASSES on the real ledger; seeded spike reddens; skip-with-note proven; baseline committed with three-component provenance; additive nominal metric lands with every pre-existing aggregate field byte-identical. |

## 1. Card J-A — `core/stop_ramp.py` (new pure module)

Two total, non-raising functions:

* `nominal_stop_step(velocity, accel_limits, dt_s)` — per-axis
  `_move_toward(v, 0.0, max_accel*dt_s)`. The symbol is IMPORTED from
  `navigation/velocity_shaping.py` rather than re-implemented, so the ramp and
  the shaper cannot drift apart. Rate derives from `MotionShapingConfig.limits()`
  (passed in); zero new constants. Malformed velocity/limits/dt fail closed to
  the exact all-axis zero — the ramp's own terminal value, so failing closed can
  never produce motion.
* `enforce_monotone_stop(previous, candidate)` — returns `None` (caller must
  HARD_STOP) on any magnitude increase, sign flip, non-finite value, or
  malformed shape.

**Measured.** `tests/test_stop_ramp.py`, 12 tests. Bit-equality against an
INDEPENDENTLY RETYPED copy of the 60ecea2 hunk (`git show
60ecea2:...velocity_shaping.py` lines 20-24 + 97-120) over a 520-point seeded
grid — retyped, not imported, so the equality cannot go vacuous when somebody
edits the live `_move_toward`.

**Finding, recorded not fixed.** Zero is reached in
`ceil(|v|/(a*dt))` steps **plus at most one float-residue tick**: iterated
`_move_toward` subtraction leaves ~1e-16 on the tick exact arithmetic predicts as
zero (e.g. `-3.0` at `a=1.2, dt=0.25` → `-3.33e-16`). Snapping it would BREAK the
bit-equality contract, so the module inherits it and the test states the real
bound. Runtime consequence is one extra ramp tick, three orders of magnitude
below `_is_zero_command`'s 1e-9.

## 2. Card J-B — severity split, flag-gated default OFF

### 2.1 What landed

* **`core/hard_stop.py`** — `NOMINAL_STOP = 3` **APPENDED**; `CLEAR=0`,
  `PROXIMITY_STOP=1`, `HARD_STOP=2` unmoved and pinned by test. The finalize
  **tail is now explicitly fail-closed**: `CLEAR` returns the candidate,
  `PROXIMITY_STOP` and `NOMINAL_STOP` take their own branches, and EVERYTHING
  ELSE falls to the untouched HARD_STOP branch with its resets. Before this card
  the tail returned the candidate for any severity that was not
  HARD/PROXIMITY — appending a member without this hardening would have opened a
  pass-through (adjudication #3, verified in the source). Byte-identical for
  every reachable input today. `NOMINAL_STOP` additionally requires a
  `previous_command` and passes only what `enforce_monotone_stop` accepts.
* **`navigation/velocity_shaping.py`** — additive `stop=` keyword taking the
  step FUNCTION (`nominal_stop_step`), so `core` keeps its one-way dependency on
  this module and no import cycle is created. `emergency=True` wins over `stop=`
  and is byte-identical. An untrusted stop stage that returns anything
  non-finite, non-braking or sign-flipping collapses to the emergency zero.
* **`core/motion_shaping.py`** — `nominal_stop_ramp: bool = False`, validated as
  a boolean in both `__post_init__` and `from_mapping`. Absent from
  `configs/robot.yaml`; no config value moved.
* **`runtime.py`** — the predicate split at `_dispatch_active`. The emergency set
  is UNCHANGED (proximity `stopped` ∨ arbiter e-stop ∨ input-health latch ∨
  `active is None`); only a zero INTENT with no emergency arm asserted, under the
  flag and with shaping enabled, becomes `nominal_ramp`. Per-tick **re-gate**:
  the ramp candidate goes back through the untouched `apply_reactive_safety` +
  TTC verdict (`_regate_nominal_stop`), `owner_orbit=False` deliberately (that
  is the gate's owner-EXEMPTION path, so declining it is strictly stricter). Any
  stop verdict — `'stopped'`, or a zeroed translation without the label —
  preempts to the untouched emergency path with exact `(0,0,0)` on the SAME tick
  plus every reset obligation. The gate's disposition (never the raw candidate)
  is what is actuated and what the shaper is re-synced to.
  **Resume-reset**: `_reset_motion_shaper` clears the ramp flag, and the first
  non-ramp tick zeroes the shaper before shaping.
* **`evals/companion_nav/runner.py`** — `_DispatchReplica._shape` mirrors the
  split UNDER THE FLAG, classifying on the INTENT (operand parity), with the
  same per-tick re-gate and monotone boundary. The flag-OFF block is byte-
  untouched, post-chain operand and all.
* **`tests/test_nominal_stop_wiring.py`** — 21 tests including the
  `STOPPING_PREDICATE_PIN` symbol digest (REACTIVE_SAFETY_PIN pattern) over
  twelve symbols across BOTH machines, plus an operand-parity assertion on the
  live sources. *(AF-1, 2026-08-11: was 17 tests over six symbols. Mini-lane
  AF-1 added the TTC-only preemption property (one function, four approach
  geometries) and six pin symbols — both `_regate*` bodies and the three
  threshold helpers. No pre-existing digest moved; see §2.4.)*

### 2.2 Flag-off byte identity — PROVED

Full 11-scenario FOLLOW_BENCH_V1, scratch results dir, no ledger append:

```
follow_success 7/9   mean_band_fraction 0.708782386458857   jerk 1.2187
min_pedestrian_surface_m 0.5299999999999998   personal_space 2.3
hard_collision 0   pedestrian_contact 0   reactive_gate_stop_total 2   navigate 2/2
```

Every value byte-identical to the committed `dd2e857` row. Reproduced twice: in
the main tree and, after J-C landed, in a lane-isolated worktree.

Two call-site details that KEEP this true and were found by existing tests
reddening: the flag-off dispatch still calls `shaper.step(...)` and
`finalize_command(...)` with their historical keyword sets (the new `stop=` /
`previous_command=` arguments are passed only on the flag-ON branches). Two
pre-existing tests wrap those callables with the old signatures; passing the new
keywords unconditionally reddened them, which is exactly the identity property
the standing rule asks for.

### 2.3 Flag-ON — the pre-registered MISS

| criterion | bar | measured | verdict |
|---|---|---|---|
| `mean_rms_commanded_jerk_mps3` | ≤ 1.05 | **1.0813** | **MISS** |
| `min_pedestrian_surface_m` | == 0.5299999999999998 | 0.5299999999999998 | pass (bit-identical) |
| `personal_space_time_total_s` | 2.3 | 2.3 | pass |
| `hard_collision_total` | 0 | 0 | pass |
| `pedestrian_contact_total` | 0 | 0 | pass |
| `follow_success` | ≥ 7/9 | 7/9 | pass |
| `reactive_gate_stop_total` | == 2 | 2 | pass |

**This is STOP-and-report.** The bar was not renegotiated and nothing was tuned
toward it. The flag remains default OFF; the code is inert until an owner flips
it (§8 open question 1).

**Attribution of the miss (measured, 5 arms, identical geometry, scratch only).**
The design cell's 1.0039 was measured WITHOUT the two closures skeptic 1 and the
synthesizer then made normative. Both cost jerk:

| arm | operand | re-gate | jerk | safety metrics |
|---|---|---|---|---|
| E flag-off control | — | — | 1.2187 | all bit-identical |
| B design-cell reconstruction | post-chain command | no | **1.0156** | all bit-identical |
| C | post-chain command | yes | 1.0234 | all bit-identical |
| D | intent | no | 1.0468 | all bit-identical |
| **A shipped as specified** | **intent** | **yes** | **1.0813** | all bit-identical |

Read: the re-gate costs +0.0078, operand parity costs +0.0312, and together
+0.0657 — they interact super-additively. Arm B reproduces the design cell's
region (1.0156 vs the reported 1.0039, a monkeypatch-vs-wired difference). So the
miss is entirely the price of the two SAFETY closures the record made binding,
not a defect in the ramp. Every arm holds follow 7/9, min_surface
0.5299999999999998, gate stops 2, dwell 2.3, contacts 0, collisions 0.

The comfort win is real but smaller than pre-registered: **1.2187 → 1.0813,
−11.3%.**

**Owner decision needed.** Three admissible outcomes, none of which this lane may
pick: (1) accept 1.0813 and flip the default, re-pinning the jerk baseline
DOWNWARD with 2x2; (2) hold the flag OFF, keep the wiring inert; (3) authorize
re-opening the operand/re-gate design — which means re-opening adjudications #2
and #4 and is a safety decision, not a tuning one.

### 2.4 Safety properties — each proven able to FAIL

Seeded in a lane-isolated worktree; clean → seeded → restored, every time:

| property | seeded violation | clean | seeded | restored |
|---|---|---|---|---|
| same-tick HARD preemption, arm 1 | `'stopped'` verdict check deleted | pass | **fail** | pass |
| same-tick HARD preemption, arm 2 | zeroed-translation check disabled | pass | **fail** | pass |
| resume-reset | shaper no longer zeroed before resume | pass | **fail** | pass |
| fail-closed finalize tail | pre-J-B open tail restored | pass | **fail** | pass |
| monotone boundary at finalize | `enforce_monotone_stop` bypassed | pass | **fail** | pass |
| stopping-predicate symbol pin | replica operand silently altered | pass | **fail** | pass |
| jerk ratchet (J-C) | margin widened to swallow the spike | pass | **fail** | pass |
| **TTC-only preemption (AF-1)** | TTC verdict call deleted from `_regate_nominal_stop` | pass | **fail ×2** | pass |

**A gap this table did not cover, found by the Fable audit and closed by
mini-lane AF-1 (2026-08-11).** Row 1 and row 2 above both drive the
`apply_reactive_safety` half of the re-gate. The TTC half had no test and no pin
symbol: deleting `return self._time_to_collision_gate(gated, observation,
proximity_state)` from `_regate_nominal_stop` left **208 of 208** pre-AF-1
safety-adjacent tests green and every one of the six original pin digests
UNMOVED. The mutant now dies twice — the pin reddens (`_regate_nominal_stop`
digest moves) and the new property test reddens on all four geometries, on two
independent assertions either of which is sufficient (the ramp candidate never
reaches the TTC verdict, so only one verdict is evaluated per tick instead of
two; and `_nominal_stop_preempt_ticks` stays 0). Re-verified clean → mutant → restored
in a lane-isolated tree copy; `runtime.py` in the working tree was never
modified (sha256 identical before and after). Not a live defect: the shipped
code applies the TTC verdict and the flag is default OFF. This was a RATCHET
gap.

**A test was strengthened because a mutant survived.** The first attempt at the
preemption seed did NOT redden: one injection tripped both preemption arms, so
deleting either left the other to kill the mutant. The property is now two
tests, each isolating one arm (`'stopped'` label with the command untouched; and
zeroed translation while the state stays `'clear'`, which is the input-health /
stale-telemetry shape of the gate's refusal). Both now die individually.

## 3. Card J-C — ratchet, attributed re-pin, additive metric

* **`scripts/ci_gate.py`** — `follow-bench-jerk-ratchet`, registered as a HARD
  gate in both the commit and nightly tiers, mirroring
  `evaluate_latency_ledger` / `evaluate_latency_ratchet`. Reads the latest
  SHIPPED follow-bench ledger row carrying `mean_rms_commanded_jerk_mps3`; reds
  iff `> baseline * LATENCY_TAIL_MARGIN` (1.20 **by reference** — no second
  tolerance constant, asserted by test); skips with a note when no such row
  exists; errors (never passes) on a malformed or non-finite value, or on a
  baseline with no provenance. Live result:
  `1.2187 <= 1.46244 (baseline 1.2187 x 1.2)` — **PASS**.
* **`evals/companion_nav/results/jerk_baseline.json`** (new) — 1.2187 with the
  three-component provenance, both bit-exact anchors, the refutation of E6's
  band-edge guess, `does_not_prove`, and the "re-pin only DOWNWARD, with 2x2"
  clause.
* **`evals/companion/duplex_v1/run_duplex_v1.py`** —
  `FOLLOW_BENCH_POST_SPEED` gains `mean_rms_commanded_jerk_mps3: 1.2187` with
  the full attribution comment (`+0.09` terminal-approach floor at 60ecea2,
  `+0.23` P0-A instant-zero at 6bd945d, `+0.33` E6-dynamics × instant-zero), and
  the correction of E6's band-edge explanation on the record. Additive: the
  three keys the duplex gate reads are untouched, and a test now holds the
  mirror, the baseline JSON and the ledger row to the same value.
* **Additive nominal metric** — `StepRecord.emergency` (default False),
  `EpisodeMetrics.rms_commanded_jerk_nominal_mps3`,
  `metrics.rms_commanded_jerk_nominal_mps3()` (same second difference, skipping
  every window that touches an emergency step, `None` — not zero — when nothing
  qualifies), and `mean_rms_commanded_jerk_nominal_mps3` +
  `nominal_jerk_episode_count` in the report aggregate and the ledger row. The
  gated field stays the INCLUSIVE mean, deliberately (§3.3: gating only the
  nominal variant would blind the ratchet to a bug spraying spurious hard stops).
* **`tests/test_ci_gate_jerk_ratchet.py`** — 16 tests (15 functions, one
  parametrized ×2). *(AF-1, 2026-08-11: the doc said 17; the collected count is
  16. Counting error only — no test was added, removed or changed.)*

**Fresh-run gate (4), lane-isolated worktree, scratch results dir:**

```
flag OFF  jerk 1.2187  NOMINAL 0.4818 (11/11 episodes)  band 0.708782386458857  7/9 ...
flag ON   jerk 1.0813  NOMINAL 1.0839 (11/11 episodes)  band 0.7068216021451316  7/9 ...
```

Every pre-existing aggregate field byte-identical in name and value; the
aggregate key set gained exactly `mean_rms_commanded_jerk_nominal_mps3` and
`nominal_jerk_episode_count` (asserted against the committed report). The
committed ledger still has **7 rows** — no append. ci_gate's hard-safety output
string is unchanged.

**The split is itself evidence for §3.1's diagnosis.** Flag-off inclusive 1.2187
vs nominal **0.4818**: ~60% of the comfort number lives on emergency-adjacent
ticks. With the flag on the two converge (1.0813 / 1.0839) because those ticks
stopped being emergencies — which is precisely the mechanism the card claims.

## 4. does_not_prove

* The flag-OFF replica classifies stops on the POST-CHAIN command while the
  runtime classifies on the INTENT. That pre-existing divergence is RECORDED,
  not fixed — fixing it moves the pinned ledger row and is owner-gated
  (adjudication #4). Only the flag-ON split has operand parity.
* Bench-only: these are the shaper's contribution on the headless kinematic
  block. No hardware ride-quality claim.
* The 1.20x ratchet tolerates ~+22% silent creep by construction. The additive
  nominal metric and the immutable reports are the escape hatch.
* The flag-ON arms were measured with `nominal_stop_ramp` injected via
  `dataclasses.replace` on the runner's `MotionShapingConfig` — the same
  mechanism `BenchFeatures` already uses. Equivalent to the YAML key (which
  `from_mapping` accepts and a unit test covers), but not literally a YAML run.
* End-to-end resume is byte-equal at the SHAPER, which is where the record
  places the claim. It is NOT byte-equal at the pre-gate smoother: a nominal
  stop is not a hard stop, so it does not run the HARD reset obligations. Stated
  and tested explicitly rather than left in a diff.
* The `+0.29` navigate_crossing_ped residual inside the first attribution
  component is attributed BY ELIMINATION (§8 open question 10); it is not
  single-hunk isolated, and this lane did not isolate it.
* No claim is made about jerk under `person_aware_nav`, `yield_aside`, or any
  other batch flag; only `nominal_stop_ramp` was exercised.

## 5. Files touched (this lane only)

New: `src/parcel_robot/core/stop_ramp.py`, `tests/test_stop_ramp.py`,
`tests/test_nominal_stop_wiring.py`, `tests/test_ci_gate_jerk_ratchet.py`,
`evals/companion_nav/results/jerk_baseline.json`, this status doc.

Modified: `src/parcel_robot/core/hard_stop.py`,
`src/parcel_robot/core/motion_shaping.py`,
`src/parcel_robot/navigation/velocity_shaping.py`,
`src/parcel_robot/runtime.py`, `evals/companion_nav/runner.py`,
`evals/companion_nav/metrics.py`, `evals/companion_nav/run_follow_bench_v1.py`,
`evals/companion/duplex_v1/run_duplex_v1.py`, `scripts/ci_gate.py`.

MUST-NOT-TOUCH honored: `navigation/reactive_safety.py`, `navigation/collision.py`,
`navigation/follow.py`, `instructnav/**`, `evals/nav_instruct/**`, all
`configs/**`, every frozen manifest, every existing ledger row. `follow.py` was
never touched — it belongs to Y-2 in Wave 3, and no handoff proved necessary.

## 6. ci_gate — and the concurrent sibling lane

Baseline before starting (fresh): **PASS**, 3390 passed, ruff 7/7/new 0, 4 digest
sentinels intact.

Final `--tier commit` in the shared working tree: **FAIL on 2 gates, BOTH owned
by the concurrent W1-D15 lane**, which is mid-flight in the same tree:

* `ruff` — `new 1 -> evals/nav_instruct/person_cell.py::ISC004` (a D15-C file).
* `default-suite` — `1 failed, 3454 passed`:
  `tests/test_e4_evidence_seams.py::test_navigator_overrides_defaults_to_empty_and_is_a_closed_set`,
  which reads the `ALLOWED_NAVIGATOR_OVERRIDES` frozenset that D15-B edits in
  `evals/nav_instruct/runner.py`.

Every other gate green, including the new one.

**Isolation proof.** A detached worktree at `dd2e857` carrying ONLY this lane's
14 files: `ruff` **7 violations, baseline 7, new 0**; `follow-bench-jerk-ratchet`
**PASS**; `frozen-digest-sentinels` **4/4 byte-identical**;
`tests/test_e4_evidence_seams.py` **13 passed**; the lane + safety-adjacent
selection (`test_stop_ramp`, `test_nominal_stop_wiring`,
`test_ci_gate_jerk_ratchet`, `test_core_hard_stop`, `test_motion_shaping`,
`test_velocity_shaping`, `test_dynamic_layer`, `test_sa2_live_pipeline`,
`test_e2_safety_wiring`, `test_e6_owner_band`, `test_duplex_v1`, `test_ci_gate`)
**206 passed**. The worktree's other failures are all `FileNotFoundError` on
git-ignored BARN/asset artifacts that a fresh worktree does not carry — verified
by reading the exception, and green in the main tree.

Net: the two red gates are the sibling's to close; this lane adds zero ruff
violations and zero test failures. A re-run once both Wave-1 lanes have landed is
the authoritative number.

## 7. For the Fable audit (§7 items aimed at this lane)

* Flag-off bench row byte-identity: reproduce it yourself —
  `run_follow_bench_v1.py --out <scratch>` and compare all seven pinned values.
* The stopping-predicate symbol pin exists and covers both machines:
  `STOPPING_PREDICATE_PIN` in `tests/test_nominal_stop_wiring.py`, twelve symbols
  across `runtime.py` and `evals/companion_nav/runner.py`, AST-normalised, with a
  regeneration command and log in its docstring. *(AF-1: six at the audit, six
  more added by the audit's own finding — the `_regate*` bodies and the
  threshold helpers. No pre-existing digest moved.)*
* The refute-first target on this lane is the flag-ON MISS: it is reported, not
  negotiated, and the flag is default OFF. If you can show 1.0813 is an artifact
  of the harness rather than of the specified machine, that is a finding — the
  five-arm table in §2.3 is where to start.
