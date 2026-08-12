# Fable audit — Wave 1 (D15 lane + J lane), 2026-08-11

Pre-registered protocol (FOLLOWUP_DESIGNS.md §7 / NEXT_BATCH_PLAN.md). Base
dd2e857; Wave-1 diff uncommitted.

## Verdict: **CONFIRMED — both lanes**, with 2 should-fix items (neither a
live defect) dispatched as mini-lane AF-1.

1. **Fresh ci_gate (Fable's own run): PASS — 3472 passed, every hard gate
   green**, including the new `follow-bench-jerk-ratchet` at its attributed
   re-pin. Matches both executors' reports.
2. **Ownership: clean.** Every changed file traces to a card's OWNS block in
   the record (the six outside my first-pass list are all explicitly in
   J-B/J-C's OWNS). One declared deviation (e4 allowlist pin moved by exactly
   one name, comment names the card) — accepted; VS-4 repeats it in Wave 2.
3. **Adversarial pass (3 skeptics, 34 refutation attempts): no blocking
   findings.** The stop-path lens attempted 12 refutations — races between
   severity classification and dispatch, hostile gates that amplify the ramp,
   unknown severity values, flag-off byte-path perturbation, a full scratch
   re-run of the flag-off bench (byte-identical) and the flag-ON miss
   (reproduced 1.0813 — the miss is real, not a harness artifact). All failed
   to refute.

## Findings (dispatched to AF-1)

- **[should-fix] J-B — the TTC half of the re-gate is unprotected.** Proven
  by mutation: silently deleting the TTC verdict from
  `runtime._regate_nominal_stop` leaves all 208 safety-adjacent tests green
  and the STOPPING_PREDICATE_PIN unmoved (the pin covers
  `_nominal_stop_ramp_tick` but not the `_regate*` bodies it calls). Not a
  live defect — shipped code applies TTC and the flag is default OFF — but
  the promised ratchet does not cover it. Fix: add the `_regate*` symbols +
  threshold helpers to the pin, plus one TTC-only preemption property test.
- **[should-fix] D15 status doc — overstated trace floor.** §3's "min
  clearance … 1.2000 exactly, never below" over-generalizes: the sweep's
  1.1000 rows are the bystander's *placement* (robot never moves,
  along-route 0.000 — it never approached below the floor), and the
  declared-owner yield floor is exactly 1.2 only after 6-dp rounding
  (person_cell.py:365). Fix: restate §3 precisely (placement vs approach;
  report the unrounded floor).
- **[note] Record §3.2 wording:** "resume dynamics byte-equal" is true at the
  SHAPER only (the smoother is not reset by a nominal stop — disclosed and
  tested by the lane; safety unaffected, every subsequent tick re-gated).
  Record should carry the narrower wording.
- **[note] Cap scope:** the D15-B speed cap covers the main grid-act emit
  path; recovery-path commands bypass the cap (but not the gate — safety
  unaffected). Documented as a known limitation; person-set sourcing between
  cap and gate differs (cap: NavObservation extras; gate: SimObservation) —
  H-1 will unify when people are actually published.
- **[note] Trivial:** jerk-ratchet test count is 16 (15 fns, one ×2), doc
  says 17.

## Standing owner decisions (unchanged, not blocking Wave 2)

- Jerk: accept 1.0813 (flag on) vs hold OFF. Fable's leaning: accept.
- H-1: authorize publishing people to the planner (moves frozen rows).
- pedestrian_group 0.75 band gate: refused as provably unreachable (oracle
  ceiling 0.616) — awaiting owner ruling (Y-4 memo will price options).

## AF-1 closure

Mini-lane AF-1 (executor: Claude Opus, 2026-08-11). Four dispatched items, all
four closed. **Not committed.** No `src/` file, no `evals/` file and no config
was modified: every finding was a RATCHET or a RECORD gap, exactly as the audit
classified them, and nothing here contradicts that reading.

### 1 — [should-fix] J-B, the TTC half of the re-gate — CLOSED

**Pin extended, six symbols added, no pinned digest moved.**
`STOPPING_PREDICATE_PIN` (`tests/test_nominal_stop_wiring.py`) goes from six
symbols to twelve, same AST-normalised convention, with the regeneration log
carrying the reason:

| added symbol | digest |
|---|---|
| `runtime.py::RobotRuntime._regate_nominal_stop` | `581b4141…` |
| `runtime.py::_is_zero_command` | `5e97a33d…` |
| `runtime.py::_finite_command_values` | `505f33dd…` |
| `runtime.py::_command_translates` | `1490a9fe…` |
| `companion_nav/runner.py::_DispatchReplica._regate` | `42470992…` |
| `companion_nav/runner.py::_is_zero` | `c75bc180…` |

The three pre-existing runtime digests and the three replica digests were
re-generated and are byte-identical to their audited values — the pin was
widened, never re-baselined.

**New property test:**
`test_the_ttc_verdict_alone_preempts_a_nominal_ramp_on_the_same_tick`, one
function over four approach geometries (head-on, oblique, slow-but-close,
lateral-crosser). The stop is injected through the TTC verdict
ALONE, structurally rather than by staging:

* `apply_reactive_safety` never reads `observation.dynamic_agents`, so a
  declared track can only reach the TTC gate. Both authorities are OBSERVED
  (pass-through wrappers returning the real values), never injected, and the
  test asserts on the real return values that the geometric gate never says
  `'stopped'` and never zeroes a translating command.
* The pre-gate smoother is put at exact zero first — the ordinary mid-ramp
  state (intent zero, smoother collapsed, actuator still coasting down the
  ramp). The tick's first gate pass therefore carries a non-translating
  command, and `time_to_collision_verdict` can only return `'stopped'` for a
  moving command, so the first pass cannot produce the emergency whatever the
  geometry. The ramp candidate, which IS moving, can.
* Asserted: the re-gate's own verdict is exactly `(scale 0.0, 'stopped')`, the
  first pass's is not, and the tick ends in HARD preemption — exact
  `ZERO_COMMAND` at `set_target`, `_last_shaped == (0,0,0)`,
  `_nominal_stop_ramping False`, `_nominal_stop_preempt_ticks` +1.
* Non-vacuity is inside the test: the identical tick with the track parked at
  12 m ramps on and dispatches a non-zero command.

**Mutant kill — the auditor's own mutant, re-applied.** Deleting
`return self._time_to_collision_gate(gated, observation, proximity_state)` from
`_regate_nominal_stop` (runtime.py:4790):

| run | pre-AF-1 view | AF-1 pin | AF-1 property test |
|---|---|---|---|
| clean | 208 passed | pass | 4 passed |
| **mutant** | **208 passed — survives** (and all six ORIGINAL pin digests verified UNMOVED) | **FAIL** (`_regate_nominal_stop` digest moves) | **FAIL ×4** |
| restored | 208 passed | pass | 4 passed |

Full selection (12 safety-adjacent files) clean and restored: **213 passed**.
The mutant now dies twice over. Two independent assertions in the property test
each detect it on their own: the re-gate never reaches the TTC verdict
(`len(verdicts) == 1`, not 2) and the ramp is never preempted
(`_nominal_stop_preempt_ticks` stays 0).

Method: clean → mutant → restored was run in a lane-isolated rsync copy of the
tree, precisely so a concurrent Wave-2 lane could never observe a mutated
`runtime.py`. The working tree's `runtime.py` sha256 is
`5b074123b45296a80354d48bff2d2f16ac799cec4416876fda19b6f9a900b9ba` before,
during and after — it was never written to.

### 2 — [should-fix] D15 status doc, trace floor — CLOSED

`W1_D15_STATUS.md` §3: the gate-clause row is restated as an APPROACH floor and
a new paragraph under the table carries both corrections, measured not argued:

* **Placement is not approach.** `min_clearance_m` is a minimum over the run
  INCLUDING the start pose, and the bystander is placed at exactly
  `clearance_m` from the start, so the §4.1 `1.10` rows report the PLACED value:
  undeclared, along-route **0.000**, the robot never moves; declared,
  along-route **2.0037**, it detours and never closes below its start clearance.
* **The 1.2 is rounded.** Re-measured with `person_cell.py:365`'s 6-dp rounding
  removed, the declared-owner (`owner_track`, flag ON, clearance 1.2632) yield
  floor is **1.2000000000000002 m** (`0x1.3333333333334p+0`) = `person_stop_m` +
  `2.220446049250313e-16` — one ULP ABOVE 1.2, never below it.

Measurement: one scratch re-run of that single cell via `person_cell.run_cell`,
module-global `round` shadowed by the identity. No file edited, no report
written, ledger untouched. It reproduces the §4.1 C row exactly (along-route
0.0635, `compliant_cap_ticks` 207, veto fraction 0.000, `yield_hold`,
collisions 0). `person_cell.py` behaviour was NOT changed.

### 3 — [note] Record §3.2 wording — CLOSED

`FOLLOWUP_DESIGNS.md` §3.2 part 2, resume-reset clause narrowed to: byte-equal
**at the shaper** (the stage the clause names); the pre-gate velocity smoother
is not reset by a nominal stop, which is disclosed and tested by J-B and leaves
safety untouched because every subsequent tick is re-smoothed and re-gated. An
`AF-1 correction` changelog comment sits at the edit site. §3.2 is otherwise
untouched.

### 4 — [note] Trivial count — CLOSED

`W1_J_STATUS.md` §3: `tests/test_ci_gate_jerk_ratchet.py` **17 → 16** (15
functions, one parametrized ×2 — collected count verified). §2.1 and §7 were
also corrected for AF-1's own effect on the same doc:
`tests/test_nominal_stop_wiring.py` 17 → **21** tests, pin six → **twelve**
symbols, and §2.4 gains the TTC-only row plus the paragraph recording the gap
this table did not previously cover.

### Verification

* `scripts/ci_gate.py --tier commit`, final run (11:10:38Z): **FAIL on `ruff`
  only**, 4 new violations, **none of them AF-1's** —
  `evals/nav_instruct/generator.py::RUF046`,
  `evals/nav_instruct/generator.py::RUF059`,
  `tests/test_value_evidence.py::F821`, `tests/test_value_evidence.py::RUF012`,
  all in concurrent Wave-2 lane files this mini-lane never opened. Every other
  hard gate green: `hard-safety`, `frozen-digest-sentinels` 4/4,
  `latency-tail-ledger`, `follow-bench-jerk-ratchet` (1.2187 <= 1.46244),
  `model-off-non-inferiority`, `frozen-digest-integrity`,
  `mutation-panel-freshness`, `latency-tail`, and `default-suite` **3541
  passed, 9 skipped, 0 failed** (audit baseline 3472; AF-1 contributes exactly
  +4 — `tests/test_nominal_stop_wiring.py` collects 21 where it collected 17 —
  and the rest is Wave 2's, which is landing tests into this tree while AF-1
  runs).
* The Wave-2 lanes are mid-flight in the same tree, so the ruff set MOVES
  between runs: an earlier AF-1 run at 11:07:06Z showed `new 3`
  (`generator.py` ×2 + `detection_adapter/false_positive_memory.py::RUF022`,
  since fixed by its owner) and `default-suite` 3522. In both runs the red is
  entirely other lanes' and every non-ruff hard gate is green. The
  authoritative number is a re-run once Wave 2 lands.
* `ruff check tests/test_nominal_stop_wiring.py`: **All checks passed.** AF-1
  adds zero ruff violations.
* No frozen artifact, ledger row, config or manifest was read-modify-written.

### Files touched

`tests/test_nominal_stop_wiring.py` (the pin + the new property test),
`scrum/20260811/task_1/W1_D15_STATUS.md`,
`scrum/20260811/task_1/W1_J_STATUS.md`,
`scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` (§3.2 only), and this section.
Nothing else. Nothing committed.

## Fable adjudication — VS-6's two declared out-of-OWNS edits (2026-08-11)

Both ACCEPTED. `tests/test_mutation_panel_freshness.py` (`== 6` → `len(killed)
== len(mutants) >= 6`) and `tests/test_nav_instruct_scene_gen.py` (exact set →
`PLAN_SIX_DEFECTS | ADDED_DEFECTS`, additions must name a card) are strict
strengthenings, verified by diff + green run (32 passed): a mutant can still
never disappear or survive unkilled, and panel growth is now one attributed
line instead of a red build. The alternative (STOP-and-report on a count pin
that the card's declared +1-mutant deliverable necessarily moves) would have
blocked a deliverable on a triviality. Edit-and-declare was the right call;
declared honestly, adjudicated here.
