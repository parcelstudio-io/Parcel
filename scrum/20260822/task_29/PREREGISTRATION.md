# FINISH-1 — pre-registration · written BEFORE any measurement

**Card:** `README.md` (task 29) · **Executor:** Claude Opus · **Verifier:** Fable
**Baseline:** `8862220` + the uncommitted week-1 tree.
This file is written before the first run of section A's harness and before any
source edit in sections C/D/E. The harness change it names (the in-bounds
qualifier) is the only edit that precedes it, and it is a *metric*, not a
threshold: the numbers below are fixed here and are not re-cut afterwards.

## A. ROAM-1 — three tethered runs (a Go2-purchase input)

**Conditions, fixed now.** `scrum/20260822/task_23/evidence/run_roam1.py`,
scene `city_block`, `--static-city`, `--budget 120`, `--person-stop 0.7`
(P1-E's prototype value), camera ingress on with MOVE-1's 8-query batch,
`memory.path: ":memory:"`, sampled at 4 Hz, three consecutive runs, each on its
own pid-unique socket. Started through the product path
(`submit_realtime_transcript("Go explore.")`), watched through `snapshot()`.

**The tether that will be ON, and the number it will be.** The harness config
carries no `roam:` section, so `RobotRuntime.roam_config` is `{}` and
`_roam_limits` passes `tether_m=DEFAULT_ROAM_TETHER_M` into
`patrol.limits_from_safety`: **10.0 m**, with `alternate_turns=True`. That is
the value `limits_from_safety` sets and the value under test. (The prototype
profile carries the same 10.0 m explicitly.)

**Rows, pre-registered:**

| row | bound | scored on |
|---|---|---|
| **T1** path length | **≥ 5.0 m** each run | `path_length_m`, 3/3 |
| **T2** net displacement **IN-BLOCK** | **≥ 1.0 m** each run | `net_displacement_in_block_m`, 3/3 |
| **T3** contacts | **0** each run | `collision_ticks`, 3/3 |
| **T4** social zone | min person clearance **≥ 0.7 m** each run | `min_person_clearance_m`, 3/3 |
| **T5** the qualifier | **`in_bounds: true` 3/3**, `out_of_block_samples` 0 | `bounds`, 3/3 |

Both numbers are reported per run: the raw `net_displacement_m` and the
in-block `net_displacement_in_block_m`. They are equal by construction on any
run that never leaves the plane; a difference is the credit taken off the
rendered map.

**Declared in advance, so it cannot be re-cut later:** a roam is a random-ish
wander and the card's own record has a 2.05–20.67 m spread. If a run misses T2
it is reported as a miss with its number, not re-run until it passes. Exactly
three runs are scored, in the order they execute, and every run that starts is
reported.

**Seed for the qualifier (RED):** the stored untethered run
`evidence/roam_static_20260822T104354Z_armB_alternating/summary.json` (the
20.67 m run that left the scene) is replayed through the same
`in_block_metrics`. Expected: `in_bounds: false`, `out_of_block_samples > 0`, a
`left_block_at_s` near 85 s, and an in-block net far below the raw 20.67 m. A
tethered run replayed through the same function must come back `in_bounds:
true` with the two numbers equal.

**Seed for the tether guard (RED):** `tether_m=None` forced in
`patrol.limits_from_safety` reddens
`tests/test_roam1_behavior.py::test_the_tether_turns_a_patrol_back_toward_home`
(seed S9); restored byte-identically by sha256, `__pycache__` purged, green.

## E. AIR-1 — the `interrupted_at` seam

`tools/bargein_through_air.py` will read `interrupted_at` (with
`interrupted_byte` / `interrupted_t_s`) off the tee's segments for
`interrupt_p50_s`. Pre-registered seed: a capture whose segments carry
`interrupted_at` yields a **number** for that row; the same capture with the
field removed yields **`unmeasured`** with the reason naming the field. No
acoustic number is claimed by this card and no audio is played on the XVF3800.

## What this card will NOT measure

No hosted spend, no live provider session, no owner session, no robot: no Go2,
no D455, no Orin are on this host. `scripts/ci_gate.py` is the verifier's.
