# W0-B status — commissioning-only path (P0-3)

Card: `scrum/20260812/task_2/W0_PRODUCT_CARDS.md` §"Card W0-B", grounding
`scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md` §"Card W0-B" and
§"CommissioningRecordV1", under `README.md`'s global rules (esp. rule 8, no
physical arming). Executor: Opus 5. Date: 2026-08-12. **Not committed.**
Base: `7242660`. Concurrent: W0-A (`control/base.py`, `control/models.py`,
`runtime.py`, `core/input_health.py`) and two doc-only cards in
`../task_1/`; attribution note in §8.

---

## 0. Measurement status — measured for this card, NOT for the tranche

**First pass: STOP-AND-REPORT.** The `Bash` tool died host-wide mid-card
(`/tmp/claude-1000` over quota), so this card was originally delivered with
every gate marked UNVERIFIED. That was the correct call and the record of it is
kept below, because it is what the numbers in this section are a correction to.

**Second pass: measured.** Fable supplied a working command channel (the
`Monitor` tool with `TMPDIR` redirected off the full volume) and an independent
measurement that **this card did not pass as written**: 4 failed / 83 passed,
and 24 ruff findings on the five owned files. Every one is now fixed and
re-measured on this tree:

| what | before the fix pass | after |
|---|---|---|
| `tests/test_w0b_commissioning.py` + `tests/test_unitree_control.py` | **4 failed, 83 passed** | **92 passed, 0 failed** in 5.62 s |
| ruff on the five owned files | **24 errors** (5 auto-fixable) | **0 — "All checks passed!"** |
| ci_gate ruff gate (repo-wide, vs `scripts/ci_ruff_baseline.json`) | — | `new 0` from this card; see §6 G6 for the one new fingerprint, which is W0-A's |
| `test_control.py` + `test_portability_proof.py` + `test_runtime.py` (every pre-existing suite that touches `control/factory.py`, found by grep) | — | **111 passed, 0 failed** in 8.98 s, re-measured **after W0-A landed** |

Test count 87 -> 92: two from the fix pass (the teardown defect, the session
context manager) and three from the polish pass (the journal-write class).

**Still NOT run, and not mine to run: the full `ci_gate --tier commit`.** The
host disk quota still reddens ~25 unrelated tests with `OSError: [Errno 122]`
(see the baseline below), so a full-suite number from this machine would be
noise. The tranche audit runs it after the quota clears — H4.

### The original stop-report, kept for the record

**Nothing in this card was executed.** Partway through the work the execution
environment failed and has not recovered:

* A fresh **pre-edit baseline** `ci_gate.py --tier commit` did run, at
  **2026-08-13T01:06:39Z**, on the clean `7242660` tree (only untracked scrum
  files present). It came back:

  ```text
  RESULT: FAIL — 1 hard gate(s) red: default-suite
    elapsed 185.2s
  [  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
  [  PASS] HARD  hard-safety                ... collisions=0 false_arrival=0 ...
  [  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical
  [  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x ceiling
  [  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
  [  PASS] HARD  model-off-non-inferiority  23 passed
  [  PASS] HARD  frozen-digest-integrity    6 passed
  [  PASS] HARD  mutation-panel-freshness   2 passed
  [  PASS] HARD  latency-tail               6 passed
  [  FAIL] HARD  default-suite              25 failed, 3907 passed, 9 skipped,
                                            36 deselected, 11 errors in 173.80s
  ```

  The named failures are `test_viewer_panel.py`, `test_web_panel.py`,
  `test_walk_with_me_k8.py`, `test_v4s_search_cells.py`, and the visible
  exception text is **`OSError: [Errno 122] Disk quota exceeded`**. That is an
  environment fault on the host, **not** a product regression, and it was
  already there before this card edited a single byte.

* Immediately after that run the shell itself died: every `Bash` invocation —
  including `echo alive`, `true`, and `/bin/echo` — returns exit 1 with no
  stdout and no stderr, from this session and from an independently spawned
  agent. `Read`/`Write` still work, which is why the code below exists.

**Consequences, stated rather than papered over:**

| | |
|---|---|
| post-edit `ci_gate --tier commit` | **NOT RUN** — still not run (host quota, H4) |
| `pytest tests/test_w0b_commissioning.py` | NOT RUN then; **measured in the fix pass** |
| `pytest tests/test_unitree_control.py` | NOT RUN then; **measured in the fix pass** |
| `ruff check .` | NOT RUN then; **measured in the fix pass** |
| every gate verdict in §6 | UNVERIFIED then; **measured in the fix pass** |

Everything in §6 is therefore "implemented + test written", never "measured".
No claim in this document is a measured claim except the baseline block above.
The card's closing condition (a fresh green `ci_gate`) is **not met**, and this
card must not be closed until someone with a working host re-runs it. The
handoff is H4 in §9.

I did not weaken any factory gate to work around this, and I did not soften
any test to make it more likely to pass unseen.

**What was done instead of running the code.** Two independent static reviews
were commissioned over the new source and the new tests. Both returned during
the fix pass, and **both independently identified the teardown defect** that the
measured failures turned out to be (`session.close()` letting
`ControlManager.close()`'s exception escape and destroy the record), plus the
`F401` and the false yaw assertion. Static review found the same three things
execution did — which is worth recording, but it found them *after* the
stop-report, and it would not have been enough on its own: the review could not
tell me the failures were 4, nor that ruff had 24 findings.

---

## 1. The defect, and the shape of the fix

`control/factory.py:107-130` refuses to build a Unitree manager unless
`enable_lease`, `axes_commissioned`, `state_frame_commissioned` and a non-empty
`allowed_modes` are already true in configuration. `unitree_control.py:66` —
the commissioning CLI — called that same builder. So the tool whose job is to
*establish* those four facts could only run once someone had already asserted
them. Commissioning could not bootstrap; the honest operator was stuck and the
dishonest one flipped four booleans in a YAML file.

The fix is a second, separate construction path plus the evidence artifact that
closes the loop:

```text
observe (read-only, no lease, no controller)
   -> modes, rates, resting feedback
arm  (operator + serial + 3 acknowledgements + observed modes, process-local, expiring)
   -> build_unitree_sport_commissioning_session(...)  # flags may all be false
run  (ONE axis, 0.02-0.05 m/s, <= one stop budget, TTL <= production TTL)
   -> AxisSignEvidence + StopEvidence, journalled with fsync at every transition
record -> CommissioningRecordV1 (defaults fail closed)
review -> a DIFFERENT human accepts, bound to the record's content digest
apply  -> the four flags, printed for a human to paste
```

The normal builder is byte-untouched. Everything W0-B adds sits below the
existing `register_controller_factory("unitree_sport", ...)` line.

---

## 2. Contract surface (what the next cards consume)

New package `parcel_robot.commissioning` (leaf: imports `parcel_robot.control`,
`parcel_robot.models`, `parcel_robot.robot_profile`, and nothing else).

```python
# limits.py — the band, the arming token, the pure guards
MIN_LINEAR_MPS = 0.02 ; MAX_LINEAR_MPS = 0.05          # card-given
MIN_YAW_RAD_S / MAX_YAW_RAD_S                          # derived, see §3
SETTLED_LINEAR_MPS / SETTLED_YAW_RAD_S                 # derived, see §3
MAX_TTL_S = 0.35 ; DEFAULT_MAX_DURATION_S = 1.0        # production-pinned
ARMING_TTL_S = 120.0                                   # procedural
REQUIRED_ACKNOWLEDGEMENTS = {"support_rig", "fenced_area", "estop_operator"}
OPERATOR_INSTRUCTIONS: tuple[str, ...]

class CommissioningAxis(str, Enum): VX | VY | VYAW
class RefusalReason(str, Enum)   # 20 named refusals (recoverable)
class LatchReason(str, Enum)     # 10 named latches (permanent), including
                                 # TEARDOWN_FAILED and JOURNAL_WRITE_FAILED
class CommissioningRefusedError(CommissioningError)   # .reason: RefusalReason
class CommissioningLatchedError(CommissioningError)   # .reason: LatchReason

@dataclass(frozen=True) class CommissioningLimits      # cannot be widened
@dataclass(frozen=True) class CommissioningArming
    CommissioningArming.arm(operator=, robot_serial=, acknowledgements=,
                            observed_modes=(), ttl_s=, limits=, clock=)
    .assert_valid(now)   # refuses expired OR another process's token
    .with_observed_modes(modes)

single_axis_command(axis, speed) -> VelocityCommand
assert_commissioning_command(command, limits) -> CommissioningAxis   # never clamps
assert_commissioning_duration(duration_s, limits) -> float
assert_commissioning_ttl(ttl_s, limits) -> float

# record.py — CommissioningRecordV1 and the review gate
FRAME_DISCRIMINATION_YAW_RAD = asin(0.5) = pi/6        # derived, see §3
class RecordOutcome(str, Enum): FAILED (default) | ABORTED | PASSED
class ObservedDirection(str, Enum): UNCERTAIN (default) | NONE | FORWARD | ...
@dataclass(frozen=True) class AxisSignEvidence     # .sign -> int | None
@dataclass(frozen=True) class StopEvidence         # confirmed=False by default
@dataclass(frozen=True) class ObservationEvidence
@dataclass(frozen=True) class ReviewAttestation    # accepted=False by default
@dataclass(frozen=True) class CommissioningRecordV1
    .content_digest() / .is_reviewed() / .missing_evidence()
    .authorizes_configuration() / .reviewed_by(...) / .save() / .load()
commissioned_control_config(control_config, record) -> dict   # raises unless reviewed

# session.py — the armed manager
class CommissioningJournal      # append-only JSONL, fsync per line, used once
    .append / .finish           # durable path: raise on failure
    .try_append / .try_finish / .try_digest   # teardown path: report, never raise
class JournalState(str, Enum): OPENED|ARMED|MOVING|SETTLING|IDLE|LATCHED|COMPLETE
class CommissioningObserver     # read-only: a state source and NO controller
class CommissioningSession      # start / run_axis_step / record / close only

# control/factory.py — the two builders (NOT registered in the registry)
@dataclass(frozen=True) class UnitreeCommissioningSeams
build_unitree_sport_observer(config, *, seams=None) -> CommissioningObserver
build_unitree_sport_commissioning_session(
    config, safety_limits, *, arming, journal_path, session_id=None, seams=None
) -> CommissioningSession
```

### The frozen statement the audit should hold me to

> `CommissioningSession` is not a `ControlManager`, does not expose one, and
> cannot be reached from configuration. It holds its manager in `_manager`; its
> entire public surface is `start`, `run_axis_step`, `record`, `close`,
> `adopt_observation`, and read-only scalars. It has no `set_target`, `tick`,
> `snapshot`, `state_source`, `controller`, `timing`, `emergency_stop`,
> `clear_emergency_stop`, or `clear_fault`. Its builders are deliberately absent
> from `_CONTROLLER_FACTORIES`, so `create_control_manager(name, ...)` can never
> return one for any string. No module under `src/parcel_robot/` outside the
> package itself mentions `parcel_robot.commissioning` except
> `control/factory.py` (two lazy in-function imports) and `unitree_control.py`
> (the CLI). `runtime.py` mentions it nowhere.

---

## 3. Derived constants (rule 6: derive or carry provenance; no tuning to a gate)

| constant | value | derivation | pinned against |
|---|---|---|---|
| `MIN_LINEAR_MPS` / `MAX_LINEAR_MPS` | 0.02 / 0.05 m/s | **Given** by the card verbatim ("0.02-0.05 m/s"). The only two given literals. | card text |
| `FOOTPRINT_RADIUS_M` | 0.32 m | Mirrored, not imported at use sites. | `DEFAULT_ROBOT_PROFILE.footprint_radius_m` (test asserts equality) |
| `MAX_YAW_RAD_S` | 0.15625 rad/s | `MAX_LINEAR_MPS / FOOTPRINT_RADIUS_M` — tangential speed at the body-inscribing radius stays inside the same band as the linear cap | recomputed in test |
| `MIN_YAW_RAD_S` | 0.0625 rad/s | `MIN_LINEAR_MPS / FOOTPRINT_RADIUS_M` | recomputed in test |
| `SETTLED_LINEAR_MPS` | 0.010 m/s | Half the *smallest* speed ever commanded, so a robot still moving at the slowest commissioned speed can never be called settled | `MIN_LINEAR_MPS / 2` in test |
| `SETTLED_YAW_RAD_S` | 0.03125 rad/s | `MIN_YAW_RAD_S / 2`, same argument | recomputed in test |
| `MAX_TTL_S` | 0.35 s | The live production command TTL; commissioning is never *more* permissive than production, and takes the configured value when shorter | `ControlTiming().command_timeout_s` (test) |
| `DEFAULT_MAX_DURATION_S` | 1.0 s | The live `stop_timeout_s`: a step may never command motion longer than the worst case time to stop it, bounding commanded travel at `0.05 * (1.0 + 1.0) = 0.10 m` | `ControlTiming().stop_timeout_s` (test). The factory narrows the arming token's band to the *configured* `stop_timeout_s`/`command_timeout_s` before building, so the derivation holds on the real config; a session built without a band recomputes the same way. Narrowing only — `CommissioningLimits` refuses any widening. |
| `FRAME_DISCRIMINATION_YAW_RAD` | pi/6 (0.5236 rad) | A wrong velocity frame puts `v*sin(theta)` on the cross axis; that must clear the evidence floor, so `|sin(theta)| >= floor/v`, worst case `0.010/0.020 = 0.5`, hence `asin(0.5)` | recomputed in test |
| `_DRIVE_POLL_S` | 0.01 s | Half one production control period (50 Hz -> 0.02 s), so the driver is never the slow link in the loop it feeds | comment; not gate-bearing |
| `ARMING_TTL_S` | 120 s | **Procedural, not derived**, and labelled as such in the source: arming must not outlive the operator's presence at the robot. Falsifiable by operator trial; carries no safety derivation. | — |

Nothing above was chosen to make a test pass; the two given literals come from
the card, and every other number is a function of a live value in the tree.

---

## 4. Findings (three, all product-relevant, none fixed here)

**F1 — the production "settled" thresholds do not discriminate inside the
commissioning band. Total on linear, partial on yaw.**
`configs/robot.yaml` sets `settled_linear_speed_mps: 0.08` and
`settled_yaw_speed_rad_s: 0.12`; `ControlManager._state_is_stopped`
(`manager.py:1197-1201`) compares measured speed against them.

* **Linear:** 0.08 m/s is above the whole band (0.02-0.05), so at *every* linear
  speed this path can command, a still-moving robot reads as "settled".
* **Yaw:** 0.12 rad/s falls **inside** the band (0.0625-0.15625). It
  discriminates above 0.12 and is blind below it — 61% of the band by width.

**Correction, and how it was caught.** The first version of this finding — and
the test named after it — claimed the thresholds sit above the *entire* band.
That is false on yaw by my own numbers (0.12 > 0.15625 is not true), and
`test_the_commissioning_band_is_below_the_production_settled_thresholds` failed
on exactly that assertion when Fable measured it. The test is now
`test_production_settled_thresholds_do_not_discriminate_inside_the_band` and
asserts the true, sharper statement including the measured 0.61 blind fraction.
The finding survives the correction because a threshold that is blind over most
of the band is still a defect for this path; it is simply smaller than claimed.
The mitigation is unchanged and was always sized correctly: the commissioning
factory clamps its manager's thresholds to `SETTLED_*` (0.010 / 0.03125) and the
session applies its own stationarity test on top of the manager's answer.
Production values are untouched. Whether 0.08 m/s is the right settled threshold
for slow production motion remains a **product question this card did not
answer**; it goes to W0-C/W0-E as H2.

**F2 — vendor feedback can never establish an axis sign; only an operator can.**
`UnitreeSportController.update` sends `lateral_sign * vy`, and
`UnitreeSportStateSource._on_message` reports `lateral_sign * vy` — the same
sign applied to command and to feedback, both inside the vendor's own frame.
Commanding `+v` through sign `s` yields reported `s*(k*s*v) = k*v`: `s` cancels,
and the reported sign is independent of the configured one. So a self-consistent
command/feedback loop proves the plumbing, not the direction. Vendor position
(`SportModeState.position`) is in the same frame and cancels identically. The
record therefore requires an `ObservedDirection` from a human who watched the
robot, defaults it to `UNCERTAIN`, and returns `sign is None` — refusing to
authorize — without one. **This is a contract correction for the plan's
`CommissioningRecordV1` section** (H3): "axis signs" is not a purely machine
measurement.

**F3 — an `odom` vs `base_link` velocity-frame check is vacuous near zero yaw.**
The state source rotates odom velocity into the body frame by the reported yaw.
At yaw ~ 0 the two frames agree to within the noise floor, so a commissioning
run performed with the robot facing its odom origin proves nothing about
`state_frame_commissioned`. The record only reports `velocity_frame_confirmed`
when the forward step ran at `|yaw| >= pi/6` (derivation in §3) *and* the cross
axis stayed under the evidence floor. Also a plan contract note (H3).

**F4 — the previous CLI's own caps were looser than the card's band.**
`unitree_control.py` carried `COMMISSIONING_MAX_LINEAR_MPS = 0.10`,
`COMMISSIONING_MAX_YAW_RAD_S = 0.25`, `COMMISSIONING_MAX_DURATION_S = 2.0`. The
card specifies 0.02-0.05 m/s and a short duration. The new path cannot exceed
0.05 m/s / 0.15625 rad/s / 1.0 s at three independent layers (session guard,
`CommissioningLimits` construction, and the manager's clamped `ControlLimits`).

---

## 5. What each file does

**Measured** — `git diff --numstat` for tracked files, `wc -l` for new ones, both
run through the working channel. The first version of this table carried
estimates read off file lengths while the shell was down; the audit's numstat
diverged from them, and these are the corrected numbers. The estimates were
disclosed as estimates at the time and are superseded here.

| file | status | added / removed | what |
|---|---|---|---|
| `src/parcel_robot/commissioning/limits.py` | **NEW** | 523 lines | band, arming token, refusal guards, `DOES_NOT_PROVE` |
| `src/parcel_robot/commissioning/record.py` | **NEW** | 798 | `CommissioningRecordV1` + evidence types + review gate + `commissioned_control_config` |
| `src/parcel_robot/commissioning/session.py` | **NEW** | 973 | journal (durable + best-effort variants), read-only observer, armed session |
| `src/parcel_robot/commissioning/__init__.py` | **NEW** | 126 | re-exports; states the leaf-import rule |
| `src/parcel_robot/control/factory.py` | amended | **+250 / −0** | `UnitreeCommissioningSeams`, the two unregistered builders, five private helpers — all appended below the existing registration. The measured **0 removed** is the hard confirmation of the additive claim: nothing above the seam moved. |
| `src/parcel_robot/unitree_control.py` | **rewritten** | +371 / −105 | 133 → 399 lines; four subcommands (`observe`/`run`/`review`/`apply`) |
| `tests/test_w0b_commissioning.py` | **NEW** | 1582 | gate map in the module docstring |
| `tests/test_unitree_control.py` | **rewritten** | +415 / −35 | 54 → 434 lines; see the enumerated note in §8 |

Card total: **+5,038 / −140**. Every removed line is in the two files marked
"rewritten", both of which are in OWNS.

Test totals across the two test files: **92 passed, 0 failed** (5.62 s).

---

## 6. Gate evidence — MEASURED

Card gate text is quoted verbatim. All 89 tests below were executed on this
tree: **89 passed, 0 failed in 5.33 s**. Only G7 (full `ci_gate`) is unrun, and
for a stated host reason that is not this card's.

### The fix pass that got here

| measured failure | root cause | fix |
|---|---|---|
| `test_latches_when_the_stop_is_never_confirmed`, `test_a_latched_session_writes_a_latched_journal`, `test_a_latched_session_refuses_every_later_call` (3 of 4) | **Real product defect, not a test bug.** `CommissioningSession.close()` called `self._manager.close()` inside an unguarded `finally`. `ControlManager.close()` raises `ControlNotReadyError` when its stop was never delivered (`manager.py:905-907`) — so on a *failed stop*, `close()` raised, and since `record()` closes first, **the record was destroyed in exactly the case it exists to document**. In the CLI this happens inside a `finally`, so the raise would also have replaced the original `CommissioningError`. | `close()` now catches teardown failure, latches it (new `LatchReason.TEARDOWN_FAILED`; a failed shutdown *stop* keeps `STOP_NOT_CONFIRMED`), journals it, finalizes, and **never raises**. New named proof: `test_a_failed_teardown_latches_instead_of_destroying_the_record` (close twice, then `record()` still returns a `FAILED` record and the journal's last line is the latch). |
| `test_the_commissioning_band_is_below_the_production_settled_thresholds` | **My finding #1 was overstated.** `assert live.settled_yaw_speed_rad_s > MAX_YAW_RAD_S` is `0.12 > 0.15625` — false. The claim holds on linear and not on yaw. | Test renamed to `test_production_settled_thresholds_do_not_discriminate_inside_the_band` and rewritten to assert the true, sharper statement: total blindness on linear, `MIN_YAW < 0.12 < MAX_YAW` on yaw, with the measured blind fraction (0.61) pinned. Finding #1 in §4 carries the correction rather than the rename. |
| 24 ruff findings on the five owned files | 15 `ISC004` (unparenthesized implicit concatenation in my `DOES_NOT_PROVE` / `OPERATOR_INSTRUCTIONS` tuples), 3 `RUF100` (noqa codes that were never needed — `BLE001` does not fire on a re-raising handler, `S110` does not fire on a narrow `except`), 2 `RUF007` (`zip(x, x[1:])`), 2 `PYI034` (`__enter__` should return `Self`), 1 `F401` (`DEFAULT_ROBOT_PROFILE` imported but only mirrored), 1 `I001` (an in-function import block). | 23 hand-fixed, 1 auto-fixed. The `F401` fix keeps the mirror-and-pin pattern and documents why it is a literal. **0 errors remain on the owned files.** |

One more test was added alongside: `test_the_session_context_manager_latches_on_an_escaping_error`, which turns the previously untested `__enter__`/`__exit__` surface into tested surface (87 -> 89).

### The polish pass (Fable's audit finding)

The audit CONFIRMED the card with one real finding, and it is the same class one
layer down from the fix above:

| finding | what was still wrong | fix |
|---|---|---|
| `close()`/`record()` could **still** destroy the record on a **journal-write** failure | The first fix stopped `ControlManager.close()` from raising. But the latch/finalize path then wrote to the journal — `_journal.finish(...)` → `open`/`write`/`fsync` — and an `OSError` there escaped `close()`, and therefore escaped `record()`, taking the record with it. This is not hypothetical: `OSError(122) Disk quota exceeded` is what took this very host out mid-card. | Every journal write on the teardown path is now best effort. `CommissioningJournal` gained `try_append` / `try_finish` / `try_digest`, which report instead of raising. A failed write latches `JOURNAL_WRITE_FAILED` **in memory** and the record still returns, `FAILED`, carrying the step evidence it already held. An unreadable journal costs the record its `journal_digest` — which fails closed, since `missing_evidence()` then lists it — and nothing else. The on-disk journal is deliberately left non-terminal, so re-opening that path latches `PROCESS_EXIT`: a journal that could not record its own ending *is* an abandoned session. |

Three seeded-failure tests, all raising the real `OSError(errno.EDQUOT)`:

* `test_a_journal_write_failure_at_teardown_still_returns_the_record` — the named proof. Kills the journal after a good step, then asserts `close()` does not raise, `record()` returns `FAILED` with `JOURNAL_WRITE_FAILED`, the axis sign and confirmed stop **survive in the record**, the on-disk journal is unchanged and non-terminal, and re-opening it latches `PROCESS_EXIT`.
* `test_an_unreadable_journal_costs_the_digest_not_the_record` — companion: the digest degrades to `""` and `missing_evidence()` gains `journal_digest`, so the failure fails closed rather than silently.
* `test_a_live_path_journal_failure_latches_by_name` — a lost journal line *mid-session* ends the session under `JOURNAL_WRITE_FAILED`, never as a bare `OSError`.

89 -> 92 tests.

### G1 — "commissioning works while the normal flags are false"

Implementation: `build_unitree_sport_commissioning_session` requires none of the
four flags; it requires a `CommissioningArming` token instead.

| proof | what it asserts |
|---|---|
| `test_commissioning_builds_while_every_normal_flag_is_false` | with all four false/empty: the normal builder raises, the commissioning builder returns a `CommissioningSession` |
| `test_normal_factory_still_refuses_each_uncommissioned_flag` (x4, parametrized) | the untouched gates still refuse each flag with the same message |
| `test_normal_factory_still_builds_when_every_flag_is_commissioned` | **companion** — the four refusals discriminate rather than refusing everything |
| `test_commissioning_factory_clamps_limits_and_timing_below_production` | limits/timing only tighten; F1 pinned |
| `test_commissioning_factory_forces_identity_axis_signs` | a configured unverified sign never colours the measurement |
| `test_commissioning_factory_takes_modes_only_from_the_arming_token` | config `allowed_modes` is ignored; the token's modes win |

**Verdict: GREEN (measured).**

### G2 — "cannot issue multi-axis / autonomous / over-limit / over-duration commands (a seeded-failure proof for EACH refusal)"

| refusal | primary test | seeded-failure proof | control (discrimination) |
|---|---|---|---|
| multi-axis | `test_refuses_multi_axis_commands` | `test_seeded_multi_axis_command_is_refused_at_the_dispatch_boundary` — monkeypatches `single_axis_command` to emit two axes; the dispatch guard still refuses and `rig.moves == 0`, proving the refusal is the guard and not merely the enum's shape | `test_single_axis_control_passes_the_same_guard` |
| autonomous / foreign writer | `test_refuses_a_foreign_writer_and_latches` — a hijacked snapshot reporting `target_source="navigation"` latches `FOREIGN_WRITER` | the hijack **is** the seeded defect (a second writer injected mid-step) | `test_a_step_with_only_this_writer_completes` |
| over-limit | `test_refuses_out_of_band_speeds` (5 parametrized: 3 over, 2 under) | `test_seeded_over_limit_command_is_refused_again_by_the_manager` — bypasses the session guard entirely and calls `manager.set_target(vx=0.6)`; the clamped `ControlLimits` refuses independently (two layers) | `test_band_edges_are_accepted` (4 cases at the exact edges) |
| over-duration | `test_refuses_over_duration_steps` | `test_seeded_wider_limits_cannot_be_constructed` — five attempts to widen the band (linear, yaw, duration, TTL, settled) all raise | `assert_commissioning_duration(max, band) == max` in the same test |
| over-TTL | `test_refuses_over_ttl_leases` | same seeded-widening test | edge accepted in the same test |
| non-finite / zero | `test_refuses_non_finite_commands_and_durations`, `test_refuses_a_zero_command` | — | — |
| not armed / expired / foreign process | `test_refuses_an_expired_or_foreign_arming_token`, `test_commissioning_factory_refuses_without_an_arming_token` | — | `arming.assert_valid(100.5)` passes at 0.5 s of a 1 s TTL |
| missing acknowledgement | `test_refuses_an_acknowledgement...` (x3, one per required ack) | — | `_arming()` with all three succeeds |
| modes not observed | `test_refuses_motion_without_observed_modes`, `test_commissioning_factory_refuses_to_build_without_observed_modes` | — | — |
| session not started | `test_refuses_motion_before_the_session_is_started` | — | — |

Refusals **never clamp**. A commissioning run that silently clamped an
operator's request would be measuring something other than what the operator
wrote down.

**Verdict: GREEN (measured).**

### G3 — "interruption, state loss, process exit, or failed stop produces a latched failure (test each)"

| latch | test | mechanism |
|---|---|---|
| interruption | `test_latches_on_interruption` | sleeper raises `KeyboardInterrupt` mid-step (armed only after `start()`); latches `INTERRUPTED`, delivers an E-stop, refuses the next step, and `record()` reports `FAILED` |
| state loss | `test_latches_on_state_loss` | feedback returns `None` mid-step; latches `STATE_LOST` |
| **process exit** | `test_latches_when_a_previous_process_exited_mid_session` | a **real subprocess** opens a journal, writes `MOVING`, and `os._exit(9)`s. The parent's `CommissioningJournal.begin` on that path writes a durable `LATCHED/process_exit` line and raises |
| failed stop | `test_latches_when_the_stop_is_never_confirmed` | seeded `StopMove` that reports success without stopping the robot; latches `STOP_NOT_CONFIRMED` and the record carries the measured (unconfirmed) settle latency |
| latch is permanent | `test_a_latched_session_refuses_every_later_call`, `test_a_latched_session_writes_a_latched_journal` | after a latch, `start` and `run_axis_step` both raise; the journal's last line is the latch and its reason |
| **companions** | `test_a_working_stop_is_confirmed_and_measured`, `test_a_cleanly_finished_journal_refuses_reuse_without_latching` | a working stop confirms with real numbers; a clean exit yields a *refusal to reuse*, not a process-exit latch — so the latch is not simply "always latch" |

Durability: the journal is append-only JSONL, `flush()` + `os.fsync()` per line,
opened before any vendor object exists, and usable exactly once ever.

**Verdict: GREEN (measured).**

### G4 — "only a reviewed evidence record can enable normal configuration"

| property | test |
|---|---|
| defaults authorize nothing | `test_record_defaults_authorize_nothing` — a bare record lists every missing item and `commissioned_control_config` raises |
| complete but unreviewed authorizes nothing | `test_a_complete_record_still_authorizes_nothing_until_reviewed` (`missing_evidence() == ("review",)`) |
| four-eyes | `test_the_operator_cannot_review_their_own_record` |
| a rejection is not an approval | `test_a_rejected_review_authorizes_nothing` |
| review is bound to content | `test_a_review_does_not_survive_a_changed_record` — **seeded**: edit `observed_modes`, or the stop numbers, after review; the attestation unbinds |
| forged files are ignored | `test_forged_derived_flags_in_a_saved_record_are_ignored` — **seeded**: hand-edit `derived.authorizes_configuration`, `derived.reviewed`, an axis `derived.sign`, and a fabricated review block into the JSON; every derived answer is recomputed from raw fields on load, so nothing changes |
| round trip | `test_record_round_trips_and_keeps_its_digest` |
| the loop closes | `test_reviewed_record_enables_exactly_the_four_normal_flags` — the reviewed record's config output is fed straight into the untouched `build_unitree_sport_control_manager`, which accepts it |
| no input mutation | `test_commissioned_control_config_does_not_mutate_its_input` |
| F2 pinned | `test_an_axis_sign_needs_an_operator_observation`, `test_a_sign_below_the_evidence_floor_is_unknown` |
| F3 pinned | `test_the_velocity_frame_claim_is_not_discriminating_near_zero_yaw` (+ companion), `test_cross_axis_leak_refuses_the_frame_claim` |
| the CLI carries the read-only phase's evidence | `test_run_carries_the_observation_into_the_record`, `test_run_refuses_modes_the_observation_never_saw`, `test_run_refuses_a_missing_observation_file` — `observe --out` writes the evidence, `run --observation` adopts it, and armed modes must be a subset of the modes actually seen. Without this the CLI could never produce an authorizing record, because nothing would have witnessed the robot at rest. |
| end to end | `test_full_session_produces_a_record_that_enables_configuration` — observe -> arm -> three one-axis steps -> `PASSED` record -> review -> config -> normal manager builds |

**Verdict: GREEN (measured).**

### G5 — "NO path from this manager into RobotRuntime (prove it)"

| proof | kind |
|---|---|
| `test_no_module_outside_the_commissioning_seam_imports_it` | source scan of every `src/parcel_robot/**/*.py`; only `control/factory.py` and `unitree_control.py` may name the package |
| `test_the_runtime_module_never_mentions_commissioning` | text + AST over `runtime.py` |
| `test_the_commissioning_package_imports_no_runtime_or_navigation` | AST over the package: no `runtime`, `navigation`, `instructnav`, `route_memory`, `evals`, `brain` |
| `test_importing_commissioning_does_not_import_the_runtime` | **executed** proof in a subprocess: after `import parcel_robot.commissioning`, no matching module is in `sys.modules` |
| `test_session_exposes_no_control_manager_surface` | the nine-method `ControlManager` surface is absent, and no public attribute is a `ControlManager` (the test reaches through `vars()` to get the manager at all — the reach is the assertion) |
| `test_commissioning_builders_are_not_in_the_controller_registry` | neither builder is a registry value; no name resolves to one |
| `test_the_observer_has_no_controller_at_all` | the read-only phase has no controller object in the first place |

**Verdict: GREEN (measured).**

### G6 — ruff, and the suites this card's `factory.py` edit could touch

```text
ruff, the five owned files:  All checks passed!
ci_gate ruff gate (repo-wide, 2026-08-13, after W0-A landed):
    fail | 8 violation(s), baseline 7, new 1
      -> tests/test_w0a_physical_provenance.py::ISC004
```

**The owned files are clean; the one new fingerprint is not this card's.**
`tests/test_w0a_physical_provenance.py:871:13` is W0-A's new test file, which
appeared in the tree between this card's fix pass and its polish pass
(`git status` at polish time also shows W0-A's `control/base.py`,
`control/models.py`, `core/input_health.py`, `runtime.py`,
`evidence_origin.py`, `test_core_input_health.py`, `test_e2_safety_wiring.py`).
The rule is `ISC004`, the same class as 15 of my own 24 findings — the fix is
to parenthesize the implicit concatenation, one line. **Not touched here: it is
in W0-A's OWNS and this card does not edit their files.** Handoff H7.

At this card's own last clean measurement the gate read
`pass | 7 violation(s), baseline 7, new 0` — byte-identical to
`scripts/ci_ruff_baseline.json` and to the pre-edit baseline, i.e. **zero new
fingerprints from the 5,038 lines this card adds**. The 7 baseline fingerprints
are pre-existing debt in `camera_channel/` and `detection_adapter/`, untouched.

Every pre-existing suite that references `control/factory.py`'s surface (found
by grepping `tests/` for `control.factory`, `create_control_manager`,
`build_backend_control_manager`, `build_unitree_sport`,
`controller_factory_names`, `register_controller_factory`) — that is
`test_control.py`, `test_portability_proof.py`, `test_runtime.py`:

```text
111 passed, 3 warnings in 8.97s
```

The additive factory change moves nothing that existed. **Verdict: GREEN
(measured).**

### G7 — full `ci_gate.py --tier commit`

**Verdict: NOT RUN, and not this card's to run.** The host disk quota still
reddens ~25 unrelated tests (`OSError: [Errno 122]` in `test_viewer_panel`,
`test_web_panel`, `test_walk_with_me_k8`, `test_v4s_search_cells`) exactly as it
did on the pre-edit baseline in §0, so a full-suite number from this machine
measures the quota, not the tree. The tranche audit runs it once the quota
clears — H4.

---

## 7. Rule 8 (no physical arming) — what this card can and cannot reach

* Nothing here auto-arms. Motion requires, in order: a `--arm` flag, three
  acknowledgements, an operator name, a robot serial, observed modes from a
  read-only phase, a fresh journal path, and a process-local token that expires.
* The commissioning path claims the Sport lease (it must, to be the sole writer)
  only inside `CommissioningSession.start()`, i.e. after all of the above.
* Every default in the new code refuses: `RecordOutcome.FAILED`,
  `ObservedDirection.UNCERTAIN`, `ReviewAttestation.accepted=False`,
  `observed_modes=()`, `CommissioningSession` with no arming raises.
* `configs/robot.yaml` is **untouched**: `axes_commissioned`,
  `state_frame_commissioned` remain `false` and `allowed_modes` remains `[]`.
  The `apply` subcommand *prints* the configuration a reviewed record
  authorizes; a human pastes it. No code path writes those flags.
* No test in this card constructs a real vendor transport. The vendor seams used
  are the ones the vendor classes already exposed (`initializer`,
  `client_factory`, `subscriber_factory`, `message_type`), and their defaults
  remain the real SDK — so a test that forgets to inject fails on the missing
  NIC exactly as it does today, rather than silently reaching hardware.

---

## 8. OWNS compliance

Touched, all inside OWNS:

* `src/parcel_robot/control/factory.py` — additive (§5)
* `src/parcel_robot/unitree_control.py` — rewritten
* `src/parcel_robot/commissioning/{__init__,limits,record,session}.py` — the new
  commissioning record module (a package; "module" in the Python sense, and the
  repo's own convention for a surface this size — `control/`, `route_memory/`)
* `tests/test_w0b_commissioning.py` — new
* `tests/test_unitree_control.py` — see the enumerated note
* `scrum/20260812/task_2/W0B_STATUS.md` — this file

**Enumerated note — `tests/test_unitree_control.py`.** The card grants "NEW
tests"; this file already existed. It covers `unitree_control.py` and nothing
else, and `unitree_control.py` is mine to rewrite. Its single pre-existing case
(`test_commissioning_cli_closes_manager_when_shutdown_stop_fails`) pinned a
property of the old flat CLI — it monkeypatched
`build_unitree_sport_control_manager`, a call this CLI no longer makes — so it
could not survive verbatim. **The property it protected is carried forward** as
`test_a_latched_run_still_writes_its_record_and_fails_the_process`: a run that
fails mid-way still tears the session down exactly once, still writes its
record, and still exits non-zero. Flagged here rather than left for the audit.

**Enumerated note — `src/parcel_robot/control/__init__.py` was deliberately NOT
edited.** Re-exporting the two new builders would have been the natural move,
and it is the same "not literally in OWNS" grey area RM-1 hit with
`route_memory/__init__.py`. I avoided the question instead: the CLI and the
tests import from `parcel_robot.control.factory` directly. Zero lines changed in
that file.

**Handoff, not an edit — `control/models.py` (W0-A's).** The commissioning
package imports `RobotMotionState` (read-only: `.received_at`, `.sequence`,
`.velocity`, `.position`, `.yaw`, `.mode`, `.error_code`), `ControlLifecycle`,
and `ControlNotReadyError`. It defines its own types for everything else. **No
change to `models.py` is requested by this card.** See H1 for the one thing a
future card should add.

Not touched: `control/base.py`, `control/models.py`, `control/manager.py`,
`control/unitree_sport.py`, `control/state.py`, `control/adapters.py`,
`control/mock_vendor.py`, `control/__init__.py`, `runtime.py`,
`core/input_health.py`, `navigation/**`, `route_memory/**`, `evals/**`,
`configs/**`, `scripts/**`, every frozen artifact, `apply_collision_brake`, the
K0 arrival predicate.

**W0-A attribution.** At this card's start `git status --porcelain` showed only
`scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md` (modified) and two
untracked scrum paths — no W0-A source edit was present yet. Any red in
`control/base.py`, `control/models.py`, `runtime.py` or `core/input_health.py`
in a later run is W0-A's, not this card's. Two tests here **read**
`runtime.py` (text + `ast.parse`); if W0-A leaves that file mid-edit they will
fail on it, which is an attribution artifact, not a W0-B finding.

---

## 9. Handoffs

* **H1 (to W0-A / a later card):** when `EvidenceOrigin` lands on boundary data,
  `CommissioningRecordV1` should record the origin of the feedback it measured —
  a record built from `SIMULATION` or `REPLAY` evidence must never authorize
  physical configuration. Today the record has no origin field at all, which is
  the honest state of the world at `7242660`; adding one is a v1 field addition
  or a v2. **Not requested as an edit now.**
* **H2 (to W0-C, RC-4's derivation table):** three numbers from here belong in
  it — `MAX_TTL_S` is pinned to the live 0.35 s production TTL; step duration is
  pinned to the live `stop_timeout_s`; and F1 says the production settled-speed
  thresholds do not discriminate below 0.08 m/s, which bears on any slow-motion
  stop-latency gate.
* **H3 (to P-1, plan r2):** the `CommissioningRecordV1` section should absorb F2
  (an axis sign requires an operator observation; vendor feedback cancels the
  configured sign) and F3 (a velocity-frame claim needs `|yaw| >= pi/6` to be
  discriminating). Both change what the contract can honestly promise.
* **H4 (blocking, to whoever owns the host):** the test machine is out of disk
  quota (`OSError: [Errno 122]`) and the default `Bash` channel is unusable —
  `/tmp/claude-1000` is the full volume. Work continued through the `Monitor`
  tool with `TMPDIR` redirected to `~/.cache/parcel-w0b-tmp`, which is the
  recipe anyone else on this host will need. **This card's own gates are green
  (§6), but `ci_gate --tier commit` still cannot produce a meaningful number**
  until the quota is cleared; expect the same ~25 unrelated failures until then.
  The tranche audit owns that re-run.
* **H5 (to the Fable tranche audit):** the adversarial item (c) — "un-enterable
  from the autonomous runtime under fault interleavings (kill/restart
  mid-commissioning)" — is covered by the journal-poisoning test, which uses a
  real `os._exit(9)`. The one interleaving **not** covered is a kill between the
  vendor accepting a `Move` and the journal's fsync; that window is stated in
  `session.DOES_NOT_PROVE` and is why the operator instructions put a second
  human on a physical E-stop.
* **H7 (to W0-A, one line):** the repo-wide ruff gate is currently red with one
  new fingerprint, `tests/test_w0a_physical_provenance.py:871:13 ISC004`
  (unparenthesized implicit string concatenation in a collection). It appeared
  when W0-A landed, it is in W0-A's OWNS, and this card did not touch it. Same
  rule class as 15 of W0-B's own findings; the fix is to wrap the concatenated
  string in parentheses. Until it lands, `ci_gate`'s ruff gate reads
  `fail | 8 violation(s), baseline 7, new 1`.
* **H6 (new, from the fix pass — worth a look beyond this card):**
  `ControlManager.close()` raises `ControlNotReadyError` when its stop was never
  delivered or confirmed (`manager.py:905-907`). That is right for the manager,
  but it makes `close()` a *throwing* teardown, and any caller that closes
  inside a `finally` on its own error path will have its original exception
  replaced by this one. W0-B hit exactly that and now guards it locally. Other
  callers of `ControlManager.close()` (notably `runtime.py`'s shutdown, W0-A's
  file) may want the same audit. Not touched here.

---

## 10. does_not_prove

* **92 green tests are 92 tests I wrote about code I wrote.** They were measured
  (§6), but a card cannot mark its own homework, and this one has the receipts
  to prove it: the first independent measurement found 4 failures and 24 lint
  findings, and the audit that followed found a *second* record-destroying
  defect one layer below the first. Both were real, both were in the teardown
  path, and both were invisible to me. Independent measurement is the check
  that matters here, not the green number.
* The journal degradation is bounded, not free: when a journal write fails, the
  durable record of that session is permanently incomplete. The in-memory record
  survives and says so, but if *that* process then dies, nothing is left. This
  path trades a complete durable trace for the operator keeping their evidence,
  and it can only make that trade once.
* Nothing in this package has ever driven real hardware. Every proof runs
  against in-process fakes through the existing bounded vendor seams; the
  Unitree DDS transport, the real `SportClient`, and the real lease are
  unexercised by this card and remain unexercised by any card so far.
* A review attestation is a named human bound to a content digest. It is **not**
  a cryptographic signature: nothing proves the reviewer's identity, and nothing
  stops whoever holds the file from rewriting the record and re-reviewing it.
  The gate is procedural, and its strength is that the four flags cannot be set
  without *someone* producing a complete record and *someone else* accepting it.
* The journal makes an abandoned session **detectable**, not impossible. A
  process killed between the vendor accepting a `Move` and the journal's fsync
  leaves a robot this file cannot describe.
* Stop latency and distance are measured through the vendor's own feedback at
  its own rate; `distance_m` is an odometry delta (or a speed integral when
  position is unavailable) over the settle window, not ground truth.
* The record carries one `StopEvidence` — the most recent step's. That is safe
  only because an unconfirmed stop latches the session immediately, so a failed
  stop can never be overwritten by a later confirmed one; it is still a
  simplification and a per-axis stop record would be strictly better.
* `ARMING_TTL_S` (120 s) is an assumption about operator presence with no
  hazard derivation behind it, exactly the class of number the verdict's N-7
  flags across the whole plan.
* This card does not make the robot safe to move. It builds the measurement path
  for a future supervised bring-up and the receipt that bring-up produces. The
  P0 1-4 closure, the gateway, and an independent operator stop all remain
  ahead of any physical motion.
