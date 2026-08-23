# R28 — the input-class × axis table

Card AWARE-1 (`scrum/20260823/task_4`), preregistered for Fable's ratification.

Concern R28 (`scrum/20260823/task_1/CONCERNS_REGISTER.md:148`) says the
proposal *distinguishes* a recoverable translation HOLD (possibly bounded
sensing yaw) from a latched all-axis exact-zero STOP, but **no accepted
input-class × axis table exists**, so a refactor could normalise two
intentionally different axis semantics and either weaken safety or remove
useful sensing rotation.

This page is that table. It is written against the **shipped** code, not
against a proposal: every row below was read out of the runtime as it stands
at `e15e466` + wave A + this card, and the file names the line that decides
it (line numbers verified against the tree as it stands after this card's
regions landed). Nothing
here changes a gate. AWARE-1's awareness sweep obeys column 4, which is
strictly narrower than column 3.

---

## 0. What the axes already mean today (measured, not proposed)

R28's premise turns out to be *already implemented* — it had simply never been
written down, which is exactly why the concern is worth a page.

| verdict | translation (`vx`,`vy`) | rotation (`vyaw`) | decided at |
|---|---|---|---|
| `ALLOW` | permitted, subject to the reactive gate | permitted | — |
| `HOLD` | **refused** | **preserved** | `runtime.py:14048-14050` |
| `LATCHED_STOP` | refused | **all-axis exact zero** | `runtime.py:11156-11158` |

* **HOLD keeps yaw on purpose.** `_collision_safe` refuses translation by
  rebuilding the command as `VelocityCommand(vyaw=command.vyaw)` — every
  translation component is dropped and the rotation component is carried
  through untouched (`runtime.py:14049-14050`).
* **A latch is all-axis.** `self._input_health_latched` forces
  `severity = InterventionSeverity.HARD_STOP` with `candidate = shaped`
  (`runtime.py:11156-11158`), and the emergency shaping path zeroes every
  axis — the sibling `PROXIMITY_STOP` branch two lines below has to *say*
  `vyaw=gated_command.vyaw` to keep yaw precisely because the emergency
  branch does not (`runtime.py:11165`). `_input_health_latched` also enters
  `emergency_stopping` at `runtime.py:10869-10872`, which suppresses the
  nominal-stop ramp.
* A latch is cleared only by operator ack (`clear_input_health_latch`,
  `runtime.py:4892`), which re-joins on the evidence and refuses to clear
  while it still latches (`runtime.py:4905`).

So the two semantics R28 feared might be conflated are real, deliberate, and
now pinned in prose. **Rule 0: no refactor may give a `LATCHED_STOP` a
surviving axis, and none may zero yaw on a bare `HOLD`.**

---

## 1. The input classes — the complete real list

Three required inputs (`core/input_health.py:26-29`): `pose`, `scan`,
`controller_feedback`. Severity is `max()`-combined across faults
(`input_health.py:223`), so the table below is read per fault and the worst
row wins.

### 1a. Per-input classes, all emitted by `_fault_for` (`input_health.py:227`)

| # | class | action | axis rule | source |
|---|---|---|---|---|
| 1 | `missing` | HOLD | translation refused · yaw survives | `input_health.py:236` |
| 2 | `stale` | HOLD | translation refused · yaw survives | `input_health.py:249` |
| 3 | `malformed` | LATCHED_STOP | **all axes** | `input_health.py:238` |
| 4 | `timestamp_malformed` | LATCHED_STOP | **all axes** | `input_health.py:244` |
| 5 | `timestamp_in_future` | LATCHED_STOP | **all axes** | `input_health.py:247` |
| 6 | `payload_malformed` | LATCHED_STOP | **all axes** | `input_health.py:251` |
| 7 | `frame_inconsistent` | LATCHED_STOP | **all axes** | `input_health.py:253` |
| 8 | `origin_malformed` | LATCHED_STOP | **all axes** | `input_health.py:255` |
| 9 | `origin_unknown` | LATCHED_STOP | **all axes** | `input_health.py:261` |
| 10 | `sim_fixture_forbidden` | LATCHED_STOP | **all axes** | `input_health.py:264` |
| 11 | `sim_fixture_unlabeled` | LATCHED_STOP | **all axes** | `input_health.py:266` |
| 12 | `physical_input_has_fixture_label` | LATCHED_STOP | **all axes** | `input_health.py:268` |

**Exactly two classes are recoverable, and both mean the same thing: the
evidence is absent or too old.** Every other class means the evidence is
*wrong* — a boundary defect, not a gap — and every one of them latches.

### 1b. Whole-table classes (`_global_latched_fault`, `input_health.py:687`)

Emitted for **all three** required inputs at once, so they are all-axis by
construction and by severity.

| class | action | source |
|---|---|---|
| `decision_time_malformed` | LATCHED_STOP | `input_health.py:207` |
| `evidence_table_malformed` | LATCHED_STOP | `input_health.py:209` |

### 1c. Ordering classes — diagnostics, not join classes

`CommissionedScanSource` / `CommissionedPoseSource` detect stream-ordering
faults and set `payload_valid=False` (`input_health.py:442`), so they reach
the join as **row 6, `payload_malformed` → LATCHED_STOP**. The specific
reason is readable on the source (`.latched_reason`, `input_health.py:403`
scan / `:620` pose) and is what the latch record publishes — it is provenance
for the operator, never a separate axis rule.

| reason | scan | pose |
|---|---|---|
| `session_epoch_mismatch` | `input_health.py:449` | `input_health.py:662` |
| `sequence_duplicate` | `input_health.py:476` | `input_health.py:676` |
| `sequence_reordered` | `input_health.py:478` | `input_health.py:678` |
| `receipt_regression` | `input_health.py:480` | `input_health.py:680` |

A re-read of the *same* datum is exempt (`input_health.py:474`, `:674`) — the
runtime genuinely joins the same observation twice, and an earlier draft
latched the very thing an operator was clearing.

---

## 2. The AWARE-1 column — when a *discretionary* sensing yaw may be proposed

Column 3 above is what the **gate permits**. This is what the awareness sweep
is **allowed to ask for**, and it is deliberately narrower. The sweep is a
preference, not a recovery manoeuvre and not a yield: a robot that keeps
turning while its evidence is degraded looks — correctly — like a robot that
does not know something is wrong.

**Rule A — any `LATCHED_STOP` class in the verdict forbids the sweep.** All
twelve latching classes above, the two global ones, and any source that has
latched. No exceptions, and the sweep is not a way to notice the latch has
cleared: only the operator ack clears it.

**Rule B — `scan:missing` and `scan:stale` permit a bounded sensing yaw.**
That is the shape where turning is the thing that fixes the problem (a D455 is
a ~87° cone; yawing re-acquires) and where the body remains measurable while
it turns.

**Rule C — any `pose` HOLD forbids the sweep.** An arc you cannot measure
cannot be bounded, and the sweep's whole safety story is its bound. Absent or
stale pose means the sweep's own arc limit is unenforceable, so the bound
would be a claim rather than a mechanism.

**Rule D — `controller_feedback:stale` forbids the sweep;
`controller_feedback:missing` does not.** This is the one row that was
CORRECTED BY MEASUREMENT rather than reasoned to, and the correction matters:
the first draft forbade both, and measuring it on a real runtime showed the
behaviour could then never start at all. A stationary runtime publishes no
motion state — the feedback buffer is filled from the observation inside
`_dispatch_active` / `_collision_safe`, both of which need a command to run —
so feedback appears one tick *after* the first command. Demanding it
beforehand is a deadlock: the sweep would need motion in order to be allowed
to propose motion. An absent feedback on a robot at rest is the expected
state, not a fault. A *stale* one is different and is refused: stale means the
controller answered and then stopped, which on a robot mid-sweep is exactly
the open-loop turn worth refusing — and once a sweep is running, feedback is
being published, so that is the class a dying controller actually produces.

**Rule E — anything not explicitly permitted is forbidden.** The predicate is
`PERMITTED_HOLD_FAULTS`, a set of `(input, class)` PAIRS rather than a set of
exclusions, so an input class added after this page defaults to "no sweep"
until someone amends this table.

### The resulting matrix

| verdict shape | gate: translation | gate: yaw | AWARE-1 may sweep? | rule |
|---|---|---|---|---|
| `ALLOW` (no faults) | permitted | permitted | **yes**, bounded | — |
| HOLD, `scan:missing` / `scan:stale` only | refused | preserved | **yes**, bounded | B |
| HOLD, `controller_feedback:missing` only (a robot at rest) | refused | preserved | **yes**, bounded | D |
| HOLD, `scan:*` + `controller_feedback:missing` | refused | preserved | **yes**, bounded | B+D |
| HOLD including `pose:missing` / `pose:stale` | refused | preserved | no | C |
| HOLD including `controller_feedback:stale` | refused | preserved | no | D |
| any `LATCHED_STOP` class (rows 3–12) | refused | all-axis zero | no | A |
| `decision_time_malformed` / `evidence_table_malformed` | refused | all-axis zero | no | A |
| any source ordering latch (§1c) | refused | all-axis zero | no | A |
| `_input_health_latched` already set | refused | all-axis zero | no | A |

Note the asymmetry in rows 2–4, and that it is the point: the **gate** treats
every HOLD the same (yaw survives), while **AWARE-1** distinguishes them. The
sweep giving up more authority than it is owed is free; the gate giving up
less is not.

### What "bounded" means

The sweep is bounded three ways at once, all configuration with validated
limits (`navigation/awareness_sweep.py`):

1. **Rate** — one `vyaw` magnitude, defaulted well under the patrol's own
   `turn_vyaw = 0.8` (`patrol/mission.py:157`), because a sensing turn is
   slower than an avoidance turn.
2. **Arc** — a total swept angle per sweep, after which the sweep ends
   regardless of what it saw. There is no branch that can extend it.
3. **Cadence** — a minimum idle period between sweeps, so the behaviour is
   periodic rather than continuous.

None of these is a safety device and none may ever be read as one. The
reactive gate, the TTC brake and the input-health join are unchanged and
remain the only things that refuse. These bounds exist so the proposer does
not spend the body's time being refused — MOVE-1's and E2-D2's lesson.

---

## 3. What this table does not prove

It is read off the desktop tree with no robot attached. It proves what the
shipped code decides, not what a Go2 does: no stop distance, no yaw rate under
load, no D455 re-acquisition time, and nothing about whether a quadruped's
"turn in place" holds its centre well enough for the swept-volume argument in
rule B to survive contact with a real dog. Rule B is the one row that should
be re-measured on hardware before it is trusted; until then the sweep's own
suppression (rules C–E) is doing the work.
