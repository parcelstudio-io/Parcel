# ROAM-2 — "explore" covers the room · DESIGN

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Wave design:**
`../WAVE2_DESIGN_FABLE.md` §3 · **Dispatch:** `../BATCHB_DISPATCH_FABLE_4a.md`
**Executor:** Claude Opus (third resume) · **Verifier:** Fable · **HEAD:** `e15e466`
**Written:** 2026-08-22 ~17:56 EDT, before this executor edited any source file.

## (a) Purpose

ROAM-1 said it about itself: *"There is no coverage objective, no frontier, no
memory of where it has been."* This card gives the wander one preference —
**go toward the place the learned map has not seen for the longest** — and
measures what that buys as *coverage*, not as distance. The objective is one
bearing and one age handed to a pure policy; the map is read, never written;
and every way the map can fail returns ROAM-1's wander, never a stop.

## (b) Architecture fit — the named seams

| seam (file:symbol) | who calls it on the product path | direction |
|---|---|---|
| `online_map/online_map.py:OnlineSemanticMap.coverage_candidates` | `runtime.py:RobotRuntime._roam_coverage_objective` only | **reader** — derives from `last_seen_wall_s`, `surface_x/y`, `active_entries()`; touches no writer |
| `runtime.py:RobotRuntime._roam_coverage_objective` | `runtime.py:RobotRuntime._step_roam` (the 10 Hz loop thread) | reads `self._p1b_learned_map` under `self._p1b_map_lock` |
| `patrol/mission.py:PatrolSense.coverage_bearing_rad` / `.coverage_age_s` | `patrol/mission.py:sense_from_snapshot` ← `runtime.py:RobotRuntime._roam_sense` | two scalars, the whole coupling |
| `patrol/mission.py:PatrolLimits.coverage_bias` (+ 3 thresholds) | `patrol/mission.py:limits_from_safety` ← `runtime.py:RobotRuntime._roam_limits` | default **OFF** on the dataclass, **OFF** in `limits_from_safety`, **OFF** in the config read — see §c |
| `patrol/mission.py:PatrolPolicy._cruise_or_cover` | `PatrolPolicy.step`, last rung | the only rung that expresses a preference |
| `runtime.py:RobotRuntime._roam_idle_checkpoint` | `runtime.py:RobotRuntime.roam_idle_checkpoint()` → CURIO-1's `_curiosity_activity_busy` | **unchanged signature**; `advance_coverage` joins `{advance, idle}` |
| `runtime.py:RobotRuntime.ROAM_CONFIG_KEYS` + `roam_config` | `configs/robot.prototype.yaml` `roam:` block | the `coverage` key, refused by name when misspelled |

**Composition with batch A and the safety core.** The entries this card ranks
are exactly the ones **VENUE-1**'s physical frames and **P1-B**'s camera→map
writer produce (`runtime.py` P1-B region, `_p1b_learned_map`), so nothing here
knows whether the pixels came from MuJoCo or a D455. **CAP-1** owns "what the
product admits": the new roam key is added to the same `ROAM_CONFIG_KEYS`
guard CAP-1's `OVERLAY_INTRODUCIBLE_KEYS` census reads, and to
`tests/test_prototype_profile.py`'s pin, so a sixth roam key is a decision
somebody wrote down. **CURIO-1**'s region is not touched — its consumer reads a
predicate whose meaning widened, not whose shape changed. **DOOR-1**/**OT-2**
regions are untouched. `reactive_safety`, `core/hard_stop.finalize_command`
and `SafetySupervisor.validate` are **not read and not imported** by any line
of this card: the coverage objective is a *proposal* that the same gate scales
or refuses like every other patrol command.

## (c) Interfaces and contracts

```python
# online_map/online_map.py
def coverage_candidates(self, x, y, yaw_rad, *, now_wall_s=None, limit=8,
                        exclude_visible=True, max_radius_m=None
                        ) -> tuple[dict[str, Any], ...]
#   rows: entry_id, label, surface_x/y, distance_m, bearing_rad (BODY frame),
#   last_seen_wall_s, age_s (None = unknown, never 0.0), within_visibility,
#   visibility_range_m.  Ordered: known ages oldest-first, unknown ages LAST,
#   entry_id breaks ties.  Never raises; () is a real answer.

# patrol/mission.py
PatrolSense.coverage_bearing_rad: float | None = None   # body frame, like person_bearing_rad
PatrolSense.coverage_age_s:       float | None = None   # None = UNKNOWN, never 0.0
PatrolLimits.coverage_bias:                 bool  = False   # DEFAULT OFF
PatrolLimits.coverage_align_tolerance_rad:  float = 0.35    # 20 deg
PatrolLimits.coverage_min_age_s:            float = 20.0
PatrolLimits.coverage_giveup_after_s:       float = 6.0
def limits_from_safety(..., coverage_bias: bool = False) -> PatrolLimits  # OFF here too
PatrolPolicy.coverage_legs -> int ; PatrolPolicy.coverage_aligning -> bool
PatrolCommand.reason in {..., "advance_coverage", "turn_coverage"}   # two NEW reasons

# runtime.py
ROAM_CONFIG_KEYS |= {"coverage"}            # roam: {coverage: true} turns it ON by name
ROAM_COVERAGE_CANDIDATES: ClassVar[int] = 8
roam_snapshot()["coverage"] = {enabled, legs, target, label, bearing_rad, age_s,
                               distance_m, candidates}
```

**The default is the measurement — and it is OFF AT EVERY LAYER.**
`PatrolLimits.coverage_bias` is `False`, `limits_from_safety` defaults it
`False`, and `_roam_limits` reads `overrides.get("coverage", False)`. So
`PatrolPolicy` is still a pure function whose MOVE-1
(`tests/test_move1_patrol.py`) and ROAM-1 (`tests/test_roam1_behavior.py`) unit
baselines are byte-unchanged — **neither file is edited by this card** — and
the ONE thing in the tree that can turn the objective on is an explicit
`roam: {coverage: true}` in a profile.

**CORRECTED 2026-08-23 (third executor).** The 17:56 draft of this design had
`limits_from_safety` default the flag to `True`, arguing that it is the roam
behaviour's only constructor so ON there means "the prototype explores" while
every other caller of the package stays untouched. That argument is real but it
loses to the wave's standing rule (`../TASK_BOARD.md` rule 1, "defaults OFF for
behaviour"): a behaviour that switches itself on is a behaviour nobody wrote
down. See `ROAM2_STATUS.md` §2.1.

**Consequence for the measurement, and it is now stronger:** the two arms are
the same product path differing by exactly one config line, and the baseline
arm is ROAM-1 *itself* — flag-off the runtime does not even ask the map, so arm
A is not "ROAM-1 plus a query". Not two harnesses, not two policies, not
ROAM-1's commit versus this one.

## (d) Data flow and lifecycle

```
camera worker thread ──(P1-B region)──> _p1b_learned_map.observe(...)   [writer, untouched]
                                             │  self._p1b_map_lock
control-loop thread (10 Hz), _step_roam:     ▼
   safety gates → e-stop → owner command → budget → freshness   (runtime ladder)
   ── all clear ───────────────────────────────────────────────────────────┐
   coverage = self._roam_coverage_objective(observation)   # OUTSIDE _lock  │
        with self._p1b_map_lock:  learned.coverage_candidates(x, y, yaw,    │
                                     now_wall_s=time.time(), limit=8)       │
        first row with a KNOWN age wins; any failure => {}                  │
   sense = self._roam_sense(observation, elapsed, coverage)                 │
   command = policy.step(sense):  collision → person → tether → wall →      │
                                  hysteresis → _cruise_or_cover  ◄──────────┘
   with self._command_lock:  submit_motion(...)  ; idle_checkpoint =
        command.reason in {"advance", "advance_coverage", "idle"}
```

**Locks.** `_p1b_map_lock` is a **leaf** in R24's roster (`runtime.py:2906`);
its one pinned edge is `_close_lock -> _p1b_map_lock`. `_roam_coverage_objective`
keeps it a leaf: called from `_step_roam` **outside** `_lock` and **outside**
`_command_lock`, holding it across one pure query that calls nothing back into
the runtime. `PINNED_LOCK_ORDER` is unchanged; `test_the_lock_order_is_the_pinned_one`
is the proof. **Threads:** one reader (control loop), one writer (camera
worker), no new thread and no new process. **Files:** none — the map's store is
P1-B's (`PARCEL_ONLINE_MAP_PATH`) and this card never opens it.

**The stale-map rule, as code, not as a promise.** Four distinct "the map has
nothing for me" conditions — objective off, no learned map installed (the
shipping `oracle` source), no bearing, unknown age, age below
`coverage_min_age_s` — plus `except Exception` around the query, and every one
of them returns `PatrolCommand(vx=cruise_vx, reason="advance")`. There is no
branch in `_roam_coverage_objective` or `_cruise_or_cover` that can return a
stop or end a roam. `test_a_stale_map_wanders_it_never_stops` and
`test_a_map_that_raises_is_a_wander_and_never_an_ended_roam` keep it that way.

**Why coverage is asked LAST.** Everything above it in `PatrolPolicy.step` is a
**yield** — contact, a person, the tether, a wall, the hysteresis that keeps the
patrol from chattering on any of them. Coverage is the only rung that expresses
a **preference**, so it must be the rung every refusal can overrule. Putting it
anywhere else would let a map argue with a wall.

**Idle checkpoints.** `advance_coverage` joins `{advance, idle}`;
`turn_coverage` deliberately does **not** — aligning onto a new objective is the
robot deciding where to go, the same kind of moment as negotiating a blocked
lane. So the checkpoint **opens the instant a leg starts being walked**, which
is the "idle checkpoint after each coverage leg" the card asks for, and
CURIO-1's `roam_idle_checkpoint()` consumer needs **no change at all**.

## (e) Hardware compatibility — the Go2 EDU+ venue

* **Venue-independent by construction.** The objective reads
  `OnlineSemanticMap` entries — the same entries VENUE-1's physical frames
  write through P1-B's ingress. `coverage_candidates` consumes only
  `surface_x/y`, `last_seen_wall_s` and `status`; it never touches
  `SimObservation` beyond the robot pose the runtime already has, and it never
  reads sim ground truth. On the Orin the identical call returns rows derived
  from D455 detections. **Nothing in this card imports MuJoCo.**
* **The policy stays a pure function of numbers.** Its output is a
  `PatrolCommand` that passes through `limits_from_safety`'s `PatrolLimits`,
  which derives `min_person_clearance_m` / forward clearance from
  `safety.person_stop_m` / `safety.obstacle_stop_m`. On the Go2 the same
  construction carries the indoor speed cap: change `roam.cruise_vx` and
  `safety.*` in the profile, change nothing in this card.
* **Configured, not coded, on the new venue:** `coverage_min_age_s` (20 s here;
  a room the dog re-enters every 8 s wants a longer floor),
  `coverage_align_tolerance_rad` (a 12 kg quadruped's yaw settling is not a
  MuJoCo integrator's), and the map's `visibility_range_m` (8.0 m default —
  the sensor that fills the map decides it).
* **The idle-checkpoint seam is where localization lands (N31), and this card
  implements none of it.** `_step_roam`'s checkpoint transition is the one
  place per leg where the runtime already knows "a leg just ended, a leg is
  starting"; a Mid-360 pose update belongs exactly there because it is the
  moment the objective's frame can be re-based without contradicting an
  in-flight command. Named, not built.
* **UNCONFIRMED, labelled as such.** That the EDU+ bundle ships a Jetson Orin
  NX 16 GB onboard, that CPython 3.10 / JetPack is the runtime, and that
  `unitree_sdk2py` over CycloneDDS is the transport are **UNCONFIRMED** — no
  fact sheet exists in this tree. What the fetched vendor text does say:
  the Mid-360 has a **360° horizontal / 59° max vertical FOV**, a **0.1 m
  minimum and 100 m maximum detection range**, and connects over **power +
  RJ-45 Ethernet**
  (`~/.cache/parcel-fable-design/hw-facts/mid360.txt:92,98,331-334`); the Go2's
  built-in head LiDAR has a **0.05 m minimum detection distance**
  (`.../go2.txt:113`) and the platform's quoted max speed is **3.5 m/s flat**
  (`.../go2.txt:573`). None of that changes a line of this design; it is
  recorded so the numbers above are not invented later.

## (f) Test strategy → the pre-registered rows and the seeds

`tests/test_roam2_coverage.py`, three groups matching (b): **the map's one
reader** (ranking, unknown-age-sorts-last, visibility exclusion, body-frame
bearing, empty map, decayed entry, *reader-changes-nothing*); **the policy**
(default-OFF indifference, `limits_from_safety` turns it on, turn-onto-bearing,
leg counting, stale map wanders, tether outranks a leg, person and wall
outrank it, give-up-and-walk, NaN refused, adapter defaults to `None`); **the
runtime** (no learned map still roams, the map is asked and the policy steers,
`turn_coverage` is not a checkpoint, `roam: {coverage: false}` turns it off,
a raising map is a wander, a misspelled key is refused by name).
`tests/test_prototype_profile.py` pins `coverage` as the sixth roam key.
Measurement rows live in `PREREGISTRATION.md` and are measured through the
product runner only. Seeds: **S1** coverage input ignored, **S2** a stale-map
tick that stops, **S3** a coverage leg that crosses the tether, **S4** the
yield-order pin — each on a byte-identical scratch copy of `src/`.

## (g) Risks and what this design does NOT cover

1. **It is a proposer, not a planner.** One bearing to one old entry. No
   frontier, no cost map, no route. A place behind a building is approached by
   walking at it until the wall gate turns the dog away — `coverage_giveup_after_s`
   bounds the cost of that, it does not solve it.
2. **Coverage is measured over entries the map ALREADY KNOWS.** It cannot
   reward discovering a place that was never in the map, and a run that learns
   ten new places scores no better for it. Stated in `PREREGISTRATION.md`.
3. **The objective is only as good as the wall clock.** `age_s` comes from
   `time.time()` minus `last_seen_wall_s`; a reloaded map stamped on another
   host yields unknown ages, and unknown ages degrade to the wander. Correct,
   but it means a cold-started Go2 explores like ROAM-1 until it has seen
   something twice.
4. **The map may be empty on the shipping default.** `semantic_source: oracle`
   installs no learned map at all, so on `configs/navigation/default.yaml` this
   card is inert. Both measurement arms therefore run
   `navigation.config: configs/navigation/prototype.yaml`, and that is a
   condition of the number, recorded in `PREREGISTRATION.md`.
5. **Not covered:** anything on a robot (no Go2, no D455, no Orin on this
   host); whether a hosted model chooses to roam; whether the coverage
   behaviour *reads* as exploring to a person.
