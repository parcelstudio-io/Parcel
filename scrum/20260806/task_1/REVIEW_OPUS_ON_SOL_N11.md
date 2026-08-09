# Opus review of Sol 5.6 — N11 pure layer (traffic-aware placement + yield-advance pacing)

**Date:** 2026-08-06 · **Reviewer:** Claude Opus (the future integrator) ·
**Arbiter:** Fable
**Under review:** `src/parcel_robot/navigation/traffic_aware.py` (378 lines),
`tests/test_traffic_aware.py` (40 tests), and the recommended wiring seam in
[SOL_N11_STATUS.md](SOL_N11_STATUS.md).
**Nothing was edited in this round.** Every claim below was executed against
the tree with `.parcel/bin/python`.

## Verdict: **REQUEST CHANGES**

The pure layer is good work and I want it. The central guarantee — byte-identical
degradation to the static ordering when the proposer is inactive — is **sound
under adversarial float testing**, not just asserted (evidence below). The tests
are real tests, the module is honestly documented, and the "not proven" section
is the best kind.

I am requesting changes because **the recommended wiring seam is the deliverable
here** — the pure module is unreachable without it, and Sol wrote the seam as a
cited recipe for me to execute. Three of its load-bearing claims do not survive
contact with the tree: the pacing hook is measurably ~6% as effective as
advertised (B1), its time source does not exist on the path it targets (B2), and
its stop-detection predicate is string equality against a note that gets
concatenated (B3). None of these is a safety defect — RampMemory's architectural
safety argument holds and I could not construct a call sequence that emits motion
during a stop. They are efficacy and robustness defects that would burn an
integration cycle and produce a "we wired N11 and the xfail didn't move" result.

Two module-level changes are also requested (S1, S7).

---

## Blockers

### B1 — Seam 2 is masked by the runtime S-curve shaper; measured benefit is +6.4%, not "most of the ~9-tick ramp"

`SOL_N11_STATUS.md:129-165` recommends seeding `GridNavigator._last_vx` and
explicitly demotes the runtime shaper to "optional second hook, only if the
pipeline seed proves insufficient" (`:160`). The tunables table claims the seed
"recovers most of the ~9-tick ramp" (`:179`).

There are **two serial ramps**, and Sol's own citations name both but never
compose them:

- `grid_navigator.py:443-447` — hard slew, `max_linear_accel` 0.9 m/s²
  (`grid_navigator.py:74-75`) → 0.09 m/s per tick, **no jerk limit**.
- `runtime.py:3893-3898` — `SCurveVelocityShaper`, `linear_max_accel` 1.2 m/s²
  **and `linear_max_jerk` 3.0 m/s³** (`src/parcel_robot/config/robot.yaml:154-155`).

The shaper is jerk-limited, so from rest it cannot use its 1.2 m/s² cap for the
first ~0.4 s. During a pedestrian pass the actuator decays to ≈0 through the
shaper's own limits, so at release `_last_shaped ≈ 0` regardless of what the
navigator requests. Simulated with the real `SCurveVelocityShaper` at the real
config limits, cruise 0.85, dt 0.1 s, seed = 0.6087 (the value `RampMemory()`
actually returns for a 0.1 s stop):

| | distance in 2.0 s | ticks to 80% cruise |
|---|---|---|
| today (unseeded) | 1.227 m | 8 |
| Sol's Seam 2 (navigator seed only) | **1.306 m** | **7** |

**+0.079 m and one tick.** The navigator command jumps to 0.699 m/s on tick 0
and the actuator still delivers 0.030 m/s, because the shaper — not
`_last_vx` — is binding.

**Failure scenario:** I wire Seam 2 exactly as specified, the person-stop suite
stays green, and `test_go_to_the_sidewalk_with_pedestrian_traffic` still xfails
because the robot recovered 8 cm more per pass. We then have a new stateful
object on the control path and no evidence, and the natural next move is to
suspect RampMemory's tuning rather than the shaper.

**Requested change:** invert the hook ordering in the status doc. The seed must
reach `_last_shaped` (the shaper already supports exactly this —
`runtime.py:3886`, `shaper.reset(self._last_shaped)`), with the navigator seed
as the secondary. If Sol wants to preserve single-writer discipline (correct
instinct), then say so explicitly and predict the outcome: *"seeding the
navigator alone is expected to move the e2e by <10%; if it does not flip the
xfail, the shaper is the binding ramp."* A card that predicts its own null
result is honest; one that claims "recovers most of the ~9-tick ramp" without
composing the second ramp is not.

### B2 — The recommended time source does not exist on the path this card targets

`SOL_N11_STATUS.md:156-159` recommends
`observation.extras["odometry_timestamp_s"]` as `RampMemory`'s monotonic clock,
citing `grid_navigator.py:908-909` (verified — that line *reads* the key).

Repo-wide, that key is **written in exactly one place**:
`evals/external/parcel_barn_adapter.py:169`, plus three BARN test fixtures. It
is not produced by the MuJoCo sim backend, the runtime, or `headless_city` — the
three surfaces the pedestrian xfail actually runs on.

So on the target path the recipe yields `extras.get("odometry_timestamp_s")` →
`None` → `RampMemory.note_running(None, vx)` → `float(None)` →

```
TypeError: float() argument must be a string or a real number, not 'NoneType'
```

...raised from inside `NavPipeline.step` at 10 Hz. Sol cites
`grid_navigator.py:477-483` as the "loud but degrading" pattern to imitate
(it does catch `(TypeError, ValueError)`), but the RampMemory recipe at
`:150-151` has no wrapper at all.

This compounds with the module's `_advance_time` contract
(`traffic_aware.py:369-370`): **time regression raises**. A monotonic-clock
contract is correct for a tick counter and wrong for a *sensor stamp*, which can
jitter, repeat, or reset on bag loop / backend restart / clock resync. Verified:
`note_stopped(0.999999)` after `note_running(1.000000)` raises.

**Failure scenario:** the e2e run dies mid-episode with a `TypeError` from a
pacing-memory helper, and the traceback points at a pure module that is working
exactly as documented.

**Requested change:** name a time source that exists on the target path — a
pipeline tick counter × `control_dt_s` is the obvious one and Sol already lists
it as the alternative at `:158-159`; make it the *primary*. Separately, decide
the regression contract deliberately: either `_advance_time` clamps a
non-increasing stamp to `dt = 0` (and documents that a *large* backward jump
requires `reset()`), or the doc states plainly that the caller must own a
monotonic counter and never pass a sensor stamp.

### B3 — `cnote == "person_stop"` is string equality against a note that gets concatenated

`SOL_N11_STATUS.md:146-151` keys the whole hook on
`cnote == "person_stop"` (citing `pipeline.py:460-467`, now `:473-480` after
today's edits).

`pipeline.py:489-511`: when `all_ray_shield is not None`, `cnote` is rewritten
as `f"{cnote}|{shield.note}"` **before** any downstream test. So under the v8
shield config, `cnote` is `"person_stop|all_ray_clear"`:

- `cnote == "person_stop"` → **False** → the recipe skips `note_stopped` and,
  because `ramp.state` is still `"stopped"` from an earlier tick, takes the
  **`release()` branch while the person gate is still closed**;
- the pipeline's own `cnote.endswith("_stop")` at `pipeline.py:512` fails the
  same way (pre-existing, and benign only because `apply_collision_brake`
  already returned `vx = 0.0`).

No motion is emitted on that tick — `vx` is already zero and the shield operates
on zero, so RampMemory's architectural safety property is not violated. But the
*gating logic* is silently inverted, `_last_vx` gets seeded with a person inside
`person_stop_m`, and the memory's decay clock is never started, so a long stop is
never recognised as long.

**Failure scenario:** the v8/BARN-shielded config (or any future stage that
appends to `cnote`) silently disables the hold logic. The unit tests cannot catch
this — they test the module, and the module is fine.

**Requested change:** key off the brake result *before* the shield rewrites it
(capture `cnote` from `apply_collision_brake` into a separate variable), or use
`cnote.split("|", 1)[0] == "person_stop"`. Belt and braces: gate `release()` on
`observation.nearest_person_m >= self.collision.person_stop_m` as well, so the
"caller asserts the gate opened" contract is checked, not assumed.

---

## Should-fix

### S1 — `traffic_occupancy_cost` tunnels: fast agents score **exactly 0.0**

`traffic_aware.py:156-169`. The rollout samples at fixed `step_s` and tests only
sample positions. The influence band along the path has half-width
`radius_m + influence_m` = 0.3 + 0.9 = 1.2 m, so the grid steps clean over it
once `v · step_s > 2.4 m`, i.e. **v > 9.6 m/s at the defaults**. Measured
(agent crossing straight through the query point, phase-offset so no sample
lands in the band):

| agent speed | cost | closest sample to point |
|---|---|---|
| 9.0 m/s | 0.0417 | 1.125 m |
| **10.0 m/s** | **0.0000** | 1.250 m |
| 12.0 m/s | 0.0000 | 1.500 m |
| 15.0 m/s | 0.0000 | 1.875 m |

**Failure scenario:** the P3 city layer feeds `dynamic_agents` from a scene with
a scooter or a vehicle lane. A candidate lying directly on a 12 m/s path scores
zero exposure, the ranking silently reverts to traffic-blind for exactly the
agent class with the least stopping margin, and the breakdown recorded into
mission metadata reports `traffic_cost = 0.0` — so the attribution says "traffic
was considered and was clear."

The module is documented for pedestrians, but nothing in the API rejects a fast
track and `coerce_tracks` accepts any finite velocity. **Requested:** either a
CFL-style validation (`raise` when
`max_speed · step_s > 2·(min_radius + influence_m)`), or swap the point-sample
test for a segment test (closest approach of the segment `[p(t), p(t+step)]` to
the query point) which removes the failure mode entirely and is ~5 lines.

### S2 — `note_running(t, cmd.vx)` on an align tick wipes the memory it exists to hold

`SOL_N11_STATUS.md:150-151` passes the pre-brake navigator command.
`grid_navigator.py:426` sets `vx = 0.0` for the whole align branch. So an align
tick with no person present is recorded as `note_running(t, 0.0)` →
`_held_vx = 0.0` (`traffic_aware.py:318`), and a person-stop one tick later
resumes from zero.

That is precisely the compound scenario the card names: "ramp-from-zero between
passes compounds it" (`scrum/20260805/task_2/README.md`, the xfail note).
`align_enter_deg` is now 55° after task_2, so this fires less often than it would
have — but the corner-plus-pedestrian case is the one that matters.

**Requested:** skip `note_running` when the navigator note indicates align (or
hold the running maximum over a short window). Cheap either way; needs to be in
the recipe.

### S3 — No bound on sample count; a config typo becomes a control-loop stall

`traffic_aware.py:145-156` validates that `step_s` is positive and
`step_s <= horizon_s`, but nothing bounds `horizon_s / step_s`. Measured:
`step_s = 1e-5` → 300 001 samples, 59 ms **per candidate per track**. Once these
land in `configs/navigation/default.yaml` (where I would put them), a misplaced
decimal is a multi-second freeze inside `step()`.

**Requested:** raise when the sample count exceeds a stated cap (10 000 is
generous — the default is 13).

### S4 — Ranking cost at realistic candidate counts is 19–34 ms of a 100 ms tick

`approach.py:207` builds the polygon candidate grid with
`spacing = max(0.25, extent/40)` → up to ~41×41 = **1681 interior samples** for a
large sidewalk region. `rank_approach_candidates` scores every candidate with no
pruning (deliberate — `traffic_aware.py:198-200`). Measured:

| candidates × tracks | wall time |
|---|---|
| 1681 × 3 | 19.2 ms |
| 1681 × 6 | 34.4 ms |
| 400 × 3 | 4.7 ms |

This runs inside `_commit_semantic_candidate` (`pipeline.py:671`), on a tick that
already does grounding and planning, against the D8 rule "hold the integrated
onboard hot path ≤176 ms median". It is not fatal — placement is one-shot, not
10 Hz — but it is a real 20–35 ms spike that nobody has budgeted, and it will be
worse on the Orin.

**Requested:** an optional `top_k` (rank the K statically-best candidates only;
K = 32 covers every realistic geometry) or a note in the seam recipe that the
caller must prefilter. The module is the right place for this because it owns the
tie-break semantics that make prefiltering safe.

### S5 — No track staleness/TTL anywhere in the API

`TrackState` (`traffic_aware.py:50-65`) has no timestamp, and
`traffic_occupancy_cost` has no age input. `dynamic_agents` is a perception
payload that can go stale (dropped camera frame, occlusion, detector hiccup).
Nothing in the module or the recipe prevents ranking against ghost pedestrians
rolled forward from a frame that is 3 s old — and constant-velocity extrapolation
of a stale track is *confidently* wrong, not merely uninformative.

**Requested:** either an `age_s` field consumed as a confidence multiplier, or an
explicit statement in the seam recipe that the caller must drop tracks older than
a named threshold before calling (with the threshold named).

### S6 — Cited line numbers are stale, and one file path is wrong

Verified every citation. `grid_navigator.py`, `dynamic_layer.py:159`,
`collision.py`, `dynamic_costs.py:43`, `approach.py:229`, `approach.py:281`,
`test_voice_nav_e2e.py:223` — **all correct**. But:

- every `pipeline.py` citation is off by 5–14 lines, because I added a soft-import
  guard to that file earlier today (`_commit_semantic_candidate` 666 → **671**;
  `apply_collision_brake` 460 → **473**; the `_stop` zero return 499 → **512**;
  the bounds/shield block 468-497 → **481-511**);
- `relations.py:92` is `src/parcel_robot/instructnav/relations.py:92` (the sort
  *is* on line 92 — correct line, wrong package), listed among two `approach.py`
  entries that are `navigation/`, which reads as `navigation/relations.py` — a
  file that does not exist.

Concurrent-edit drift is expected and not Sol's fault; the fix is to cite
symbol + file rather than file + line for cross-agent recipes.

### S7 — "Malformed input raises `ValueError` loudly" is false on every public entry point

`traffic_aware.py:36-38` states the contract; `SOL_N11_STATUS.md:19-20` repeats
it. Measured:

| call | actual |
|---|---|
| `note_running(None, 0.5)` | **TypeError** |
| `note_stopped(None)` | **TypeError** |
| `release(None)` | **TypeError** |
| `note_running(0.0, None)` | **TypeError** |
| `traffic_occupancy_cost((None, 0.0), [])` | **TypeError** |
| `traffic_occupancy_cost((0,0), None)` | **TypeError** |
| `rank_approach_candidates(None, [])` | **TypeError** |
| `rank_approach_candidates([(1,0)], [], static_cost_fn=lambda p: "a")` | ValueError ✓ |

`coerce_tracks` gets this right (`:111-112` catches `TypeError` and re-raises as
`ValueError`); nothing else does. This matters concretely because B2's `None`
timestamp arrives as `TypeError`, and any integrator writing
`except ValueError:` around the documented contract will not catch it.

**Requested:** either coerce at the boundary the way `coerce_tracks` already
does, or amend the docstring to `(TypeError, ValueError)`. The former is better —
the recipe's caller can then use one except clause.

---

## Nits

- **N1** `traffic_aware.py:136-139` — `step_s` is not a pure resolution knob. A
  parked agent integrates to `horizon_s + step_s` (measured: 3.50 / 3.25 / 3.10 /
  3.05 for step 0.5 / 0.25 / 0.1 / 0.05), so changing the resolution silently
  re-tunes the static↔traffic tradeoff at fixed `traffic_weight`. The closed
  sample grid double-counts one endpoint. Documented, but the tunables table
  (`SOL_N11_STATUS.md:172`) presents `step_s` as cost/resolution only.
- **N2** `traffic_aware.py:337-339` — `release()`'s docstring says a long stop
  does a "full state reset"; it leaves `_last_now_s` intact (which is correct —
  the time base must survive). Say "clears the memory" to keep `reset()` the only
  thing that means full reset.
- **N3** `RankedCandidate` (`:68-77`) carries no attribution of *which* track
  drove `traffic_cost`, and no echo of the parameters used. Seam step 3
  (`SOL_N11_STATUS.md:114-117`) writes the breakdown into mission metadata for
  eval attribution; "traffic_cost 1.4" without "from track 2 at t≈1.75 s" is not
  attributable in a failure review. Nice-to-have, not required to wire.
- **N4** `SOL_N11_STATUS.md:173` derives `influence_m` 0.9 from
  `person_stop_m 1.2 − radius 0.35`. The module measures from the agent
  *surface*; the runtime gate measures `nearest_person_m`, which is a detection
  range whose reference point (centre vs surface) is not pinned anywhere. The
  numbers land within ~5 cm either way, so this is bookkeeping, not error — but
  the rationale should name the assumption.

---

## Answers to the six review angles

1. **Math.** Correct where it is defined. Monotone in proximity; agents moving
   away contribute only their `t=0` overlap (pinned); stationary agents integrate
   the full horizon (right for placement — do not park the goal on a standing
   person); zero-velocity tracks are legal and well-behaved; ties are broken
   deterministically by explicit `index`. Units are honestly described including
   the `+step_s` closed-grid bias. The one genuine hole is discrete-sample
   aliasing (S1).
2. **Byte identity — the guarantee holds, and I tried hard to break it.** Sorting
   by `(w·s, s, i)` versus `(s, i)`: IEEE-754 multiplication by a positive finite
   `w` under round-to-nearest is monotone non-decreasing, so `s₁ < s₂` can never
   yield `w·s₁ > w·s₂`. Rounding *collisions* (`w·s₁ == w·s₂` for `s₁ ≠ s₂`) are
   fully repaired by the second key element, which is `s` itself. Verified over
   200 candidates with static costs drawn from
   `{0.1, 0.1+5e-17, 1e-320 (subnormal), 1e308, 0.0, −3.0}` at
   `static_weight ∈ {1.0, 1e-300, 1e300, 3.0, 1e-8}` — ordering identical in
   every case, including the `1e300` cell where every total overflows to `inf`
   and the tie falls entirely to the secondary key. Negative static costs are
   accepted (only finiteness is checked) and do not break it. **The claim in
   `SOL_N11_STATUS.md:48-54` is correct as written.** `min()`'s first-minimum
   semantics does equal the `(static, index)` tie-break, so the
   `approach.py:229/281` swap is genuinely behaviour-preserving at `tracks=()`.
3. **RampMemory safety.** I could not construct a call sequence that emits or
   implies motion during a stop. `note_stopped` returns `None` on every gated
   tick however many (pinned); `release()` outside the `_STOPPED` state returns
   `0.0`; `held_velocity_mps` is a read-only property; `resume_scale ∈ (0,1]` and
   `commanded_vx ≥ 0` are enforced; a long stop clears the memory *while still
   stopped*; a second stop decays from the seed rather than the stale pre-stop
   value. The architectural argument in the module docstring is the right
   argument and it is true. What the module cannot do is know whether the gate
   actually opened — verified: with state `"stopped"`, `release()` returns
   0.6087 on demand. That is by design and correctly documented, which is exactly
   why B3 matters: the one assumption the module delegates to the caller is the
   one the recipe gets wrong. Time regression raises rather than clamping (B2).
   Double-application with the jerk shaper: Sol's "one writer" instinct is
   right, but B1 shows the chosen writer is the wrong one.
4. **Seam accuracy.** Citations verified individually — see S6. On the specific
   question: seeding `GridNavigator._last_vx` does **not** fight the align cut.
   `grid_navigator.py:426` forces `vx = 0.0` in the align branch and `:454`
   writes that zero straight back to `_last_vx`, so align wins cleanly and the
   seed is discarded. Safe — but silently lost, in the corner-flap case that
   motivates the card (see S2). `_last_vx` is zeroed on eight further paths
   (`:256, :277, :505, :571, :592, :627, :679, :977`), all deliberate
   restart-from-zero semantics that the seed correctly loses to. Clamping to
   `cruise_vx` in the proposed `seed_ramp` is right.
5. **`proxemic_approach.py` — recommend PARK (keep, do not wire, do not delete).**
   It solves the same problem with a different kernel (Gaussian `sigma_m` 0.45 vs
   linear `influence_m` 0.9), a different horizon (2.0 vs 3.0 s), and a different
   decay default (0.8 s vs off). Wiring both at one seam would install two
   disagreeing proxemic authorities — the same shape of defect as the three
   disagreeing "arrived" definitions D5 already made us pay for. `traffic_aware`
   should own the seam: it has the byte-identity guarantee that
   `select_proxemic_approach` structurally cannot offer (it returns `None`
   fail-closed where `min()` returned a point, so an inactive proposer *can*
   change behaviour — it can abort a placement that used to succeed), and it
   returns the breakdown the eval needs. But do **not** delete it: its TTC term
   (`proxemic_approach.py:131-143`) is genuinely additive information nothing
   else in the tree computes for a candidate pose, and `reject_cost` is the right
   shape for a later fail-closed **veto applied to the ranked winner** rather
   than a competing selector. Adjudication ask: park it with a one-line docstring
   note pointing at this review, and re-propose the veto after the ranking lands
   and the xfail has moved.
6. **API fit for the wiring I would do.** Missing, in priority order: track
   staleness (S5); a `top_k` or documented prefilter obligation (S4); per-candidate
   attribution of the driving track (N3); a config surface — every tunable is a
   keyword default today, and I would need them in
   `configs/navigation/default.yaml` under `traffic_placement:` / `yield_advance:`
   with the same named-provenance discipline the speed knobs now carry. Otherwise
   the API fits: `coerce_tracks` accepting `dynamic_costs.AgentTrack` directly
   (pinned by test) means `tracks_from_payload` output threads straight through
   with no adapter, which is the right call.

## What this review does not cover

- No closed-loop claim either way. I did not wire anything, and the xfail was not
  run. The B1 figure is a simulation of the real `SCurveVelocityShaper` at the
  real config limits under an assumed at-rest actuator, not an e2e measurement.
- I did not review `dynamic_costs.py` or `dynamic_layer.py` themselves, only the
  interfaces N11 consumes.
- Determinism was spot-checked in-process only; I make no cross-platform claim,
  and neither does Sol.
