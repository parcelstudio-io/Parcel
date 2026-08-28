# Dynamic social progress · proposed system

## Decision in one sentence

Do not solve pedestrian stalls by reducing a persistence timer. Build a
visibility-aware multi-person tracker, time-indexed probabilistic occupancy,
and a typed social-progress supervisor upstream of Parcel's existing final
reactive gate; allow learned models to rank comfortable motion, never to shrink
the independently commissioned hard stopping envelope.

This is a research design for the intended Go2 EDU+ and AGX Orin platform. It
is not a physical clearance specification and it does not authorize motion.

## What Parcel already has, and the exact gap

The current stack is more capable than a static-costmap description suggests:

- `navigation/tracker.py` has a constant-velocity Kalman state, covariance,
  Hungarian data association, confirmation/deletion lifecycle, and a named but
  unused `existence_probability` seam.
- `navigation/dynamic_costs.py` and `dynamic_layer.py` project constant-
  velocity agents over a two-second horizon and provide a TTC brake.
- `navigation/reactive_safety.py` is a direction-aware final body gate. It adds
  command-speed reaction distance, preserves the same hard stop for owner and
  stranger, and applies a nearest-person TTC brake.
- `navigation/traffic_aware.py::RampMemory` prevents the commanded-speed ramp
  from restarting at zero after every brief person stop.
- `core/yield_policy.py` accounts for a sustained social blockage and controls
  when to ask or end a mission. Its release grace is episode bookkeeping; it
  does not keep the body stopped while the gate is clear.

The blocking gap is upstream. The navigation pipeline still compresses people
to nearest distance/TTC in important paths; the mid-level collision brake is
radial for people; predicted tracks do not carry visibility, existence, role,
or a future distribution; misses age out after a fixed count; and the simulator
does not exercise reactive sidewalk groups, crosswalk authority, or elevator
phases. The present Follow controller has direct/behind formations, not a
qualified side-by-side region. Therefore the stack cannot reliably tell these
three different facts apart:

1. a person still occupies the swept corridor;
2. a person is temporarily occluded and may still occupy it; and
3. fresh sensors have explicitly observed that the corridor is free.

The third fact—not a timeout—is what should trigger a fast resume.

There is also a concrete map-release mismatch. A pedestrian return can saturate
the occupancy log odds at `4.0`; with the current `-0.45` free-ray decrement and
`0.65` occupied threshold, it takes eight unobstructed free observations to
clear that cell—about 0.8 s at 10 Hz. An occluded cell has no temporal decay and
can remain a hard obstacle indefinitely. The soft dynamic layer is removed when
tracks disappear, but it cannot reopen a hard occupied grid cell. Separately,
tracks delete after five misses, normal global replanning may wait five ticks,
and the final reactive gate reopens on one fresh clear observation. These
uncoordinated clocks explain both ghost stalls and stop/resume chatter.

The progress budgets are similarly fragmented: general no-progress is roughly
20 s, explicit no-route/obstacle commitments roughly 6 s, social patience 8 s,
and owner search 45 s. Person stops are excluded from some obstacle accounting,
while TTC-only stops, predictive reaction-ring stops, comfort creep, and
downstream runtime stops do not all enter one typed cause. A unified liveness
decision must observe the requested command, final dispatched command, planner
state, track evidence, and achieved motion rather than parse a free-form
`person_stop` note.

## Proposed authority and data flow

```text
camera detections + LiDAR clusters/free rays + odometry/time health
                              |
                              v
        fused per-person tracks with visibility and existence
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
  2–4 s occupancy distributions        semantic scene state
  CV/CA/IMM first; learned challenger  sidewalk/crosswalk/elevator
             |                                 |
             +----------------+----------------+
                              v
       bounded velocity/time-lattice or local MPC candidates
            hard chance constraint + soft social ranking
                              |
                              v
           typed social-progress and deadlock supervisor
                              |
                              v
        existing fresh-sensor reactive gate and sole writer
                              |
                              v
                       Go2 motion gateway
```

The semantic/prediction path may only remove candidates, lower speed, choose a
passing side, or request a replan. It cannot bypass the final reactive gate,
authorize road entry, infer elevator capacity from a language model, or emit
joint/velocity commands from a VLM.

## 1. Track both presence and negative evidence

Each dynamic track should carry at least:

```text
track_id, class, position/velocity/covariance, existence_probability,
last_observed_time, last_update_time, visibility_state,
owner_identity_posterior, group/flow role, sensor provenance
```

`visibility_state` is a closed enum:

- `VISIBLE`: associated camera/LiDAR evidence;
- `EXPLICIT_FREE`: fresh LiDAR rays and camera geometry cover the person's last
  occupied corridor and disagree with continued occupancy;
- `OCCLUDED`: the last state projects behind an observed occluder;
- `OUT_OF_FOV`: the sensor could not have disproved presence; and
- `STALE`: the fused bundle exceeded its age budget.

A missed detection has different meaning in every state. An unoccluded miss in
a freshly ray-cleared corridor should reduce existence rapidly. An occluded or
out-of-FOV miss should coast the track with expanding covariance. Stale data
must never provide positive clearance. This can start with a calibrated
Bernoulli/IPDA-style existence update; the first version need not be a large
learned model.

Do not stamp people into the persistent static map. Maintain three separate
surfaces:

1. static geometry and traversability;
2. live per-agent tracks; and
3. time-indexed predicted occupancy/risk.

The sensor driver must publish both obstacle returns and ray-cleared free space
with source timestamps, sensor pose/extrinsics version, expected update rate,
and an age verdict. Costmap persistence without ray clearing cannot prove an
obstacle has left; immediate deletion on one missed camera box is equally
unsafe.

## 2. Predict a distribution, not one future point

Use a measured ladder so complexity is earned by closed-loop gains.

### Baseline B0: calibrated CV/CA Kalman

Retain current constant velocity, add constant acceleration, propagate full
covariance, and report Gaussian negative log likelihood, coverage, and timing.
This is the cheap and debuggable floor.

### Baseline B1: IMM stop/go/turn mixture

An interacting multiple-model filter should mix at least constant velocity,
decelerate-to-stop, accelerate, and bounded-turn modes. It directly targets
the common sidewalk failures: a person hesitates, stops, steps sideways, or
resumes. Its output is a weighted set of occupancy tubes, not a single label
such as “will cross.”

### Baseline B2: interaction candidates

Use Social Force and ORCA as inexpensive baselines/candidate generators, and a
short velocity/time lattice with committed left/right passing hypotheses.
ORCA is useful for throughput comparison, but its reciprocal-agent assumptions
do not hold for arbitrary pedestrians, children, strollers, or a person who has
not perceived the dog. It is not the safety authority.

### Challenger B3: multimodal learned forecasting

Evaluate Trajectron++ first; AgentFormer or a real-time-oriented diffusion
model can follow only if needed. Train on consented/appropriately licensed
trajectory data plus simulator failures. Calibrate predicted event risk on
whole held-out episodes, preferably with conformal prediction sets or another
explicit coverage audit. Promotion requires improvement in contact/near miss,
false-stop time, resume latency, completion, calibration, cross-simulator
transfer, and AGX p99 deadline—not ADE/FDE or best-of-N alone.

A compact learned risk critic is appropriate only as a soft ranking term behind
the deterministic occupancy and hard envelope. It may learn that owner-
parallel motion is less socially costly than cutting between strangers; it may
not decide that a contact trajectory is safe.

## 3. Resume quickly from explicit evidence

Run tracking/fusion continuously while stopped and re-evaluate a short swept
corridor on every fresh bundle. A proposed state machine is:

```text
TRACK
  -> SLOW_YIELD              predicted occupancy exceeds slow threshold
  -> HOLD_OCCUPIED           hard corridor occupied
  -> HOLD_UNCERTAIN          recent person is occluded or inputs stale
  -> PROBE_RESUME            K fresh bundles explicitly clear short corridor
  -> COMMIT_PASSING_SIDE     choose left/right and suppress reciprocal dancing
  -> TRACK                   stable progress
  -> FORMATION_SWITCH        beside -> trailing through bottleneck
  -> REROUTE                 legal alternate route exists
  -> ASK_OWNER / SAFE_HOLD   bounded liveness budget exhausted
```

Use asymmetric hysteresis: a high-confidence/low-latency threshold may stop,
while resume requires the lower occupancy-risk threshold to hold for `K` fresh
sensor bundles. Start `K=2` for evaluation at 20–30 Hz, then calibrate; do not
encode two frames as a safety claim. `PROBE_RESUME` is a low-speed, jerk-limited
forward command whose entire swept footprint is rechecked on every fresh
frame. Return to hold immediately if evidence changes. Continue local
replanning during the hold rather than waiting for the eight-second social
patience timer.

Measure two latencies separately:

- **world-to-evidence:** actual corridor clear to first sensor bundle capable
  of showing it;
- **evidence-to-motion:** that bundle to three translating ticks and measurable
  displacement.

This separation reveals whether a delay belongs to sensing, tracking,
planning, the command shaper, or the gateway. The design target for the frozen
simulator suite is evidence-to-release p95 at most 0.40 s and evidence-to-
motion p95 at most 0.80 s, with a two-second maximum. Those are engineering
targets, not physical-safe reaction times.

The stall supervisor must classify at least `true_dynamic_block`,
`uncertain_occlusion`, `stale_sensor`, `costmap_ghost`, `reciprocal_oscillation`,
`localization_failure`, and `planner_failure`. Generic spin/reverse recoveries
should be suppressed around people; a committed passing side, formation switch,
replan, owner query, or safe hold is usually more legible.

## 4. Learn comfortable proximity without learning away safety

There is no universal literature-derived “safe proximity.” Commission the hard
person envelope from the mounted system:

```text
hard clearance >=
  swept Go2 body/leg footprint
  + relative closing speed * worst measured sense-to-command latency
  + worst measured braking distance on this gait and surface
  + calibrated tracking/localization/extrinsic uncertainty allowance
  + commissioning margin
```

Measure this for each speed, direction, gait, payload, floor friction, slope,
and sensor-health mode. Use surface clearance consistently and log the center-
distance conversion. Owner identity, crowd density, urgency, crosswalk phase,
or a learned score cannot reduce this floor.

Above the floor, learn an anisotropic soft comfort cost conditioned on bearing,
relative velocity, passing/overtaking/crossing relation, consented owner role,
group membership, sidewalk width, available escape space, density, venue, and
motion direction. Unknown identity uses stranger treatment. Gather explicit
owner settings and separately consented human preference comparisons; do not
infer protected traits, emotion, disability, or willingness to yield from
appearance. Report comfort by group/role/scenario slices and preserve a manual
more-conservative setting.

## 5. Venue-specific semantic policies

### Sidewalk companion formation

Represent “walk beside me” as a formation region, not a point target. Prefer a
consented left/right side-by-side slot when measured width and predictive risk
permit it; smoothly switch to a trailing slot through a bottleneck, opposing
group, doorway, or single-file segment, then reacquire beside. Maintain owner
identity lineage through occlusion and never switch to the nearest person by
default. Treat crowd flow as a soft route prior only. Commit a passing side for
a bounded horizon so the dog does not mirror a pedestrian indefinitely.

### Crosswalk

Use an explicit state machine:

```text
APPROACH_CURB -> WAIT_AUTHORITY -> OWNER_COMMITTED -> COMMIT_CROSS -> EXIT
```

Road entry requires a mapped crosswalk/curb region, owner commitment, explicit
signal/traffic authority, a visible/feasible exit, and sufficient time margin.
Other pedestrians entering the road never supply authority. Once committed,
do not overtake, switch formation sides, reverse, or stop for comfort alone in
the traffic lane; preserve forward progress toward the safest legal exit when
the hard dynamic envelope permits it. The hard collision gate always wins.
Occluded vehicle sensing, traffic signal integration, local law/ODD review, and
closed-course validation are separate prerequisites. Physical crosswalk use is
therefore **NO-GO**.

### Tight elevator

Use another explicit resource/phase state machine:

```text
QUEUE_OFFSET -> VERIFY_OPEN -> ALLOW_EGRESS -> VERIFY_CAPACITY
 -> ENTER_TRAILING_OWNER -> PARK_HOLD -> EXIT
```

Fuse two door-region LiDAR ROIs with visual door/floor semantics; disagreement
means wait. Keep out of the egress lane until riders exit, enter behind rather
than abreast of the owner, cap speed, avoid spin/reverse in the cabin, and hold
stance while the car moves. A temporary camera miss behind the door jamb is
occlusion, not clearance. Door reopening, reflective walls, crowd capacity,
identity occlusion, closing-door intrusion, rail gaps, and threshold foot
placement require dedicated tests. A 2-D boarding success cannot qualify Go2
threshold locomotion.

## 6. Compute placement on an AGX Orin system

All motion-critical computation stays local. Initial design rates to profile,
not assume, are:

- direct safety sensors and final gate: at least 50 Hz;
- fusion/tracking and explicit-free-space updates: 20–30 Hz;
- forecasting/local planning: 10–20 Hz;
- segmentation: 10–15 Hz, asynchronously age-gated; and
- conversational/semantic explanation: event/turn rate.

Start with TensorRT-capable detector/segmentation models such as an audited
PeopleNet-like detector and PIDNet/SegFormer-sized segmentation, then profile
the exact camera resolution, concurrent audio/model load, RAM/VRAM, power,
thermals, and p50/p95/p99 deadlines on AGX Orin 64 GB. The predictor consumes
fused world tracks, not full video, so CV/IMM is inexpensive and a compact
Trajectron++ challenger is plausible. Starlink and hosted APIs are outside
tracking, planning, safety, clearance, traffic authority, and elevator control.

The present Go2 backend cannot supply this path yet: it is observation-only,
refuses motion, publishes pose/LiDAR while leaving person/owner channels
unmeasured, and explicitly reports the owner invisible. Simulator work must
therefore include the same runtime/gateway contract and a realistic perception
adapter; oracle person tracks cannot be mistaken for mount readiness.

## 7. Simulator learning and promotion program

Use different simulators for different questions:

1. the repository deterministic 2-D harness for unit mechanisms and failure
   refuters;
2. SocialGym 2.0 for fast policy/curriculum sweeps;
3. HuNavSim for reactive groups and non-cooperative behavior across ROS-capable
   simulators;
4. SocNavBench for untouched real-pedestrian-trajectory replay;
5. Parcel/Unitree MuJoCo for the exact Go2/gateway/locomotion contract;
6. Isaac Sim/Lab for camera/LiDAR/latency/appearance/domain randomization; and
7. timestamped Stage-0 bags and shadow-mode replay before controlled motion.

Train in one human-motion family and qualify in different simulators and real
replay. Randomize actor density and 17–40-person overload; stop/go, reversals,
cut-ins, non-cooperation, groups and strollers; occlusion, ID switches, ghosts,
duplicate/missed tracks and camera/LiDAR skew; sidewalk width/curbs; signal
phase, owner hesitation and occluded vehicles; elevator capacity/door cycles,
glass and reflective walls; command latency, braking variation, gait bob,
extrinsics, odometry drift and localization jumps.

The full frozen qualification set should contain 1,200 solvable episodes: 400
each for sidewalk, crosswalk, and elevator, plus 240 adversarial stress cases.
Split by geometry, actor behavior, appearance/sensor mutation, and template—not
frames or only random seeds. Pair every obstacle-departure case with a frozen
counterfactual. Promotion floors include:

- zero contacts, hard-envelope violations, unauthorized road entries,
  entry-before-egress, capacity violations, false unreachable results, and
  avoidable deadlocks;
- at least 99% evidence-valid resume success;
- false-block time at most 1% of progress-demand time overall;
- at least 90% task success overall and 85% per venue;
- sidewalk owner-formation fraction at least 0.80;
- no more than 2% of episodes with over two seconds of false block; and
- local-stack p99 at most 50 ms with no 100 ms deadline misses.

Zero contacts in 1,200 simulation episodes gives only an approximate one-sided
95% upper event-rate bound of 0.25%; it does not establish zero real-world risk
or human comfort.

## Immediate build slice: `SOCIAL-PROGRESS-1`

Build this default-off, simulator/shadow-only slice after the existing
same-path simulator contract:

1. Add `DynamicTrackV1` and `VisibilityEvidenceV1`, including source time,
   covariance, existence, occluded/out-of-FOV/explicit-free state, and owner
   identity lineage.
2. Publish synchronized LiDAR marking and clearing rays plus camera observation
   frusta; implement and calibrate existence updates on replay.
3. Replace scalar upstream person state with per-track occupancy tubes while
   preserving the existing final reactive gate unchanged.
4. Add the typed `SocialProgressV1` state machine, two-bundle evidence release,
   probe resume, continuous replan, cause-coded stalls, committed passing side,
   and formation switch.
5. Add sidewalk/crosswalk/elevator task automata. Keep crosswalk/elevator and
   side-by-side product authority default off.
6. Benchmark CV, CV/CA IMM, ORCA, and Trajectron++ in the frozen matrix. Promote
   by closed-loop/calibration/timing gates only.
7. Replay exact product observations and commands through the gateway in shadow
   mode; then follow the separate physical commissioning ladder.

See `DESIGN.md` for the smaller preregistered desktop experiment and
`SOURCES.json` for primary-source provenance.
