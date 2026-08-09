# N1 — Classical / model-based navigation research

**Agent:** N1 (Claude Opus research stand-in)  
**Date:** 2026-08-07  
**Scope:** Nav2 Smac / NavFn, Regulated Pure Pursuit (RPP), MPPI, Hybrid A*,
State Lattice, fail-closed collision monitors, quadruped stop-distance — and
what that implies for Parcel’s `grid_v1` vs an isolated Nav2 sidecar.  
**Method:** Independent web review of primary Nav2 docs/repos, Hybrid-A*
literature, Unitree/CMU Go2 references, plus Parcel source/docs cross-check.
This is research guidance, not a safety certification or a commit to migrate
authority.

---

## 1. Executive verdict

Keep **`grid_v1` as the production-path planner and CI reference**. Treat
Nav2 as an **exclusive challenger sidecar** behind a narrow goal/path/cmd
protocol — not a v1 authority migration. Steal Nav2’s *ideas* into Parcel
immediately: post-smoother fail-closed collision monitor, speed-dependent stop
envelope, RPP-style curvature/obstacle speed regulation, and (only when
footprint/heading constraints bite) Smac Hybrid / Lattice as a planner
challenger.

That matches the binding adjudication in
[`scrum/20260805/task_1/ADJUDICATION.md`](../../../20260805/task_1/ADJUDICATION.md)
(D1: no Nav2 authority migration in v1; adopt collision-monitor stage and
speed zones additively) while aligning with the later
[`TARGET_ARCHITECTURE.md`](../TARGET_ARCHITECTURE.md) Nav2-sidecar sketch.

---

## 2. Component map (classical stack)

| Layer | Nav2 option | Parcel today | Recommendation |
|---|---|---|---|
| Global path (holonomic / circular) | NavFn or Smac 2D | Rolling-grid A* (`grid_v1`) | **Keep `grid_v1`**; NavFn/Smac2D only as sidecar A/B |
| Global path (SE2 / curvature) | Smac Hybrid-A* or State Lattice | Circular footprint A* | Sidecar challenger when non-circular / turn-radius matters |
| Local tracking | RPP | Forward-preferred + rotate-first + speed caps | **Port RPP regulations** into Parcel; RPP plugin in sidecar baseline |
| Local optimization | MPPI | Soft dynamic costs + TTC gate | Sidecar **challenger** for dynamic scenes; never sole safety |
| Final geometry gate | Collision Monitor | Proximity + TTC before shaper (ordering gaps remain) | **Parcel-owned fail-closed monitor after every smoother** |
| Locomotion | (external) | Unitree Sport Move/Stop | Keep Sport; classical stack only emits body twist |

---

## 3. Planners

### 3.1 NavFn

NavFn is a wavefront Dijkstra / optional A* holonomic planner on a weighted
costmap. It assumes a **circular** robot (or circular approximation) and is
described as the long-stable ROS Navigation Function port.

- Docs: [NavFn Planner](https://docs.nav2.org/configuration/packages/configuring-navfn.html)
- Package note: [nav2_navfn_planner README](https://github.com/ros-navigation/navigation2/blob/main/nav2_navfn_planner/README.md)
- Plugin selection guide: [Setting Up Navigation Plugins](https://docs.nav2.org/setup_guides/algorithm/select_algorithm.html)

**Parcel read:** Functionally closest to `grid_v1`’s cost-aware grid A*. NavFn
does **not** buy kinematic feasibility for a quadruped body that cannot
instantaneously track arbitrary piecewise-linear paths at speed. Migrating to
NavFn alone is unlikely to fix Parcel’s attributed failures
(grounding/termination/calibration), which adjudication already notes are not
indictments of grid A*.

**UNVERIFIED:** Whether NavFn Dijkstra vs A* (`use_astar`) would measurably
change Parcel city SPL / timeout rates on the frozen nav-instruct corpus —
no Parcel A/B exists.

### 3.2 Smac family (2D / Hybrid-A* / State Lattice)

Smac provides three A*-based planners in one optimized framework:

| Plugin | Role | Typical robots (per Nav2) |
|---|---|---|
| `SmacPlanner2D` | Cost-aware 2D A* (+ smoother / multi-res) | Circular diff / omni |
| `SmacPlannerHybrid` | Hybrid-A* with Dubins / Reeds-Shepp, SE2 footprint checks | Ackermann, **legged**, high-speed curvature-limited |
| `SmacPlannerLattice` | State Lattice over offline minimum control sets | Non-circular diff/omni/ackermann/legged/custom |

Primary sources:

- [Smac Planner overview](https://docs.nav2.org/configuration/packages/configuring-smac-planner.html)
- [Smac State Lattice config](https://docs.nav2.org/configuration/packages/smac/configuring-smac-lattice.html)
- [nav2_smac_planner README](https://github.com/ros-navigation/navigation2/blob/main/nav2_smac_planner/README.md)
- Algorithm selection table: [select_algorithm](https://docs.nav2.org/setup_guides/algorithm/select_algorithm.html)
- Discourse announcement (lattice beta history, ~50–200 ms planning claims):
  [Nav2 State Lattice Planner](https://discourse.openrobotics.org/t/nav2-new-state-lattice-planner-beta/23143)
- Paper framing cost-aware Smac: Macenski et al.,
  [Cost-Aware Kinematically Feasible Planning…](https://arxiv.org/html/2401.13078v2)
- ROSCon slides: [On Use of Nav2 Smac Planners (PDF)](http://download.ros.org/downloads/roscon/2022/On%20Use%20of%20Nav2%20Smac%20Planners.pdf)

Foundational Hybrid-A* idea (continuous SE2 state in discrete cells; drivable
rather than purely grid-optimal): Dolgov et al.,
[Practical Search Techniques in Path Planning for Autonomous Driving](https://ai.stanford.edu/~ddolgov/papers/dolgov_gpp_stair08.pdf).

**Parcel read:**

- **Smac 2D** ≈ stronger cousin of `grid_v1`; useful sidecar baseline, weak
  reason to delete in-process planning.
- **Hybrid-A*** is the first Smac variant that matches Nav2’s own “legged”
  recommendation when minimum turning radius and full-footprint SE2 checks
  matter (tight indoor, curb approach, high cruise).
- **State Lattice** is the right challenger when Go2 needs custom primitives
  (limited reverse, prefer forward, constrained in-place yaw) via a minimum
  control set — not when you only need circular free-space paths.

**Caveats flagged by Nav2 ecosystem (adopt as risk register):**

- Lattice paths are tied to costmap resolution; downsampling / naive smoothing
  can break feasibility (docs + community issues).
- Smoothers without SE2 footprint re-check can make non-circular plans
  infeasible in tight spaces
  ([navigation2#5330](https://github.com/ros-navigation/navigation2/issues/5330)).
- Author-reported 50–200 ms class times are **not** Parcel Orin + GPU
  co-residency proof. **UNVERIFIED** on Parcel hardware.

---

## 4. Controllers

### 4.1 Regulated Pure Pursuit (RPP)

RPP extends pure pursuit with:

- curvature-based linear speed regulation (corner overshoot reduction);
- obstacle/cost proximity slowdown;
- adaptive lookahead vs speed;
- explicit collision checking along the pursuit arc
  (`use_collision_detection`, TTC-to-carrot style limits);
- suitability claimed for differential, **legged**, and Ackermann bases
  (omni lateral capability underused vs DWB).

Sources:

- [Regulated Pure Pursuit config](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html)
- [nav2_regulated_pure_pursuit_controller](https://github.com/ros-navigation/navigation2/tree/main/nav2_regulated_pure_pursuit_controller)

**Parcel read:** Best **interpretable deterministic controller baseline** for
a Nav2 sidecar and the best *pattern donor* for in-house tracking: Parcel
already prefers yaw-align-then-forward; RPP’s regulated scaling is the missing
comfort/safety layer between A* polylines and Sport. Prefer RPP over MPPI as
the first sidecar controller for CI bisectability.

### 4.2 MPPI (Model Predictive Path Integral)

MPPI samples noised control sequences, forward-simulates a motion model
(DiffDrive / Omni / Ackermann), scores with plugin critics, and softmax-blends
toward a control. Documented as a predictive successor to TEB / path-tracking
MPC; claimed 100+ Hz on modest Intel CPUs in upstream docs.

Sources:

- [MPPI config](https://docs.nav2.org/configuration/packages/configuring-mppic.html)
- [nav2_mppi_controller](https://github.com/ros-navigation/navigation2/tree/main/nav2_mppi_controller)
- Package index: [nav2_mppi_controller](https://index.ros.org/p/nav2_mppi_controller/)

**Parcel read:** Correct **dynamic-scene / local-optimization challenger**,
especially where soft grid costs + reactive TTC freeze or timeout. Parcel’s
own research notes already record a BARN case where stock Nav2 MPPI solved a
world Parcel timed out on
([`MODEL_AND_RL_DECISION.md`](../MODEL_AND_RL_DECISION.md)) — evidence for a
sidecar A/B, **not** proof MPPI is globally better or safe on Go2.

Hard constraints for any MPPI trial:

1. Hard obstacle / collision critic must remain non-negotiable (no weight that
   can undercut geometry).
2. Penalize lateral `vy`, excess yaw, reverse, oscillation, and road intrusion
   (align with [`TARGET_ARCHITECTURE.md`](../TARGET_ARCHITECTURE.md)).
3. MPPI internal samples are **not** a product contract for learned imitation
   without an explicit export interface. **UNVERIFIED** that Parcel can
   legally/technically harvest those trajectories for BC without custom hooks.
4. DiffDrive motion model ≠ Sport gait dynamics. **UNVERIFIED** tracking error
   and stop behavior under Sport latency.

---

## 5. Fail-closed collision monitors

Nav2’s Collision Monitor sits **below** planners/controllers as a
`cmd_vel` filter: stop / slowdown / limit / approach polygons over scan/cloud
sources. Critical fail-closed behavior:

- `source_timeout` (default 2.0 s node-level; overridable per source): if no
  new data arrives in the window, **the robot is stopped**.
- `source_timeout: 0.0` **disables** that blocking mechanism (opt-out of
  fail-closed freshness).
- Invalid source also covers transform failure into `base_frame`.
- Intended as last link after velocity smoother
  (`cmd_vel_smoothed` → monitor → `cmd_vel`).

Sources:

- [Collision Monitor Node](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html)
- [Using Collision Monitor tutorial](https://docs.nav2.org/tutorials/docs/using_collision_monitor.html)
- Watchdog / fail-closed default history:
  [navigation2#3880](https://github.com/ros-navigation/navigation2/pull/3880)
- Implementation reference (invalid source → STOP):
  [collision_monitor_node.cpp](https://github.com/ros-navigation/navigation2/blob/main/nav2_collision_monitor/src/collision_monitor_node.cpp)

**Parcel read (highest leverage classical import):**

Adjudication already kept “independent collision-monitor stage ordered after
smoothing” without ROS. Current audit still finds residual-motion risk when
proximity/TTC stop meets the S-curve shaper
([`CURRENT_STACK_AUDIT.md`](../CURRENT_STACK_AUDIT.md) P0.1) and open-loop
translation risk on missing scan (P0.2). Nav2’s lesson is organizational, not
package-shaped:

1. Final monitor **after** every smoother/shaper/learned component.
2. Freshness miss / transform miss / malformed scan → **exact zero**, not
   stub fallback, on physical profiles.
3. Monitor is defense-in-depth, **not** functional-safety certification
   (Nav2 docs + Parcel target architecture both say this).

**UNVERIFIED:** Parcel’s measured end-to-end stop latency (sensor → Sport
settled) on the commissioned Go2; envelope math is incomplete without it.

---

## 6. Quadruped stop-distance

### 6.1 Physics / standards-shaped envelope (Parcel)

Parcel's base stop-distance terms have the right dimensions in `SafetyEnvelope`
([`authority.py`](../../../../src/parcel_robot/authority.py)):

```text
stop_distance(v) = r_foot + v·τ + v²/(2a) + Zs + Zr
person_stop(v)   = max(person_social_zone, stop_distance(v) + 1.4·τ)
```

The second expression is a **blocking dimensional defect**: `1.4` is declared
dimensionless and `τ` is seconds, so their product cannot be added to metres.
Replace it with a typed measured distance or `declared_closing_speed * time`.
Also verify whether the chosen center-to-surface clearance convention already
includes the footprint; otherwise `r_foot` can be double-counted. Neither
formula is a certification claim.

ISO/TS 15066 vocabulary is used as a shaping guide for reaction, braking,
sensing intrusion (`Zs`), and pose uncertainty (`Zr`). Code itself notes
**unreconciled floors**: `obstacle_stop_m` / `stop_distance_m` drift across
`robot.yaml` vs `configs/navigation/default.yaml` (`stop_distance_m: 0.8`).

Edu/docs reinforce the operational rule: any raise of `max_vx` or relaxation
of deceleration must recompute stop distance and inflation in the same change
(e.g. robotics day-03 linear mechanics; physics day-07 braking).

### 6.2 Vendor / field reality (Go2)

Unitree materials emphasize:

- L1 4D LiDAR min detection ~0.05 m; **intelligent avoidance is forward-only**;
- operator guidance to keep ≥ **2 m** from obstacles/crowds/water in manual /
  accompany modes;
- **no published braking-distance table** as a function of gait/speed/surface
  in the manuals reviewed for this note.

Sources (secondary hosts of Unitree manual text — treat as **UNVERIFIED**
against a pinned OEM PDF at procurement time):

- [Go2 User Manual (hosted PDF)](https://physical-computing-lab.net/wp-content/uploads/Go2-User-Manual.pdf)
- [ManualsLib Go2 guide](https://www.manualslib.com/guide/3774520/unitree-go2-manual.html)
- Emergency damping stop chord documented in third-party Go2 controller notes:
  [quadruped.de Go2 manuals](https://www.docs.quadruped.de/projects/go2/html/controller.html)

CMU Go2 autonomy stack (classical primitives + terrain + waypoint follow;
hardware baseline, not Parcel safety proof):

- [jizhang-cmu/autonomy_stack_go2](https://github.com/jizhang-cmu/autonomy_stack_go2)
- Design notes: waypoints must stay in the **near vicinity** or the robot can
  dead-end; collision avoidance is primitive occlusion on terrain maps
  ([CMU exploration / development environment](https://www.cmu-exploration.com/development-environment)).
- Parcel’s source ledger additionally records CMU README caveats: low-obstacle
  limits, occasional SLAM drift, camera vs LiDAR/IMU sync issues, and >1 s
  delay on an external Humble path — **re-verify on the pinned commit** before
  citing as gate numbers ([`SOURCE_LEDGER.md`](../SOURCE_LEDGER.md)).

**Parcel read:**

- Configured constant `stop_distance_m: 0.8` at `max_vx` up to ~0.9–1.0 m/s is
  **not** automatically consistent with `v²/(2a) + vτ` once Sport latency and
  gait braking differ from YAML `linear_decel`. Mark as **UNVERIFIED** until
  measured.
- Quadruped-specific extras beyond wheeled Nav2: stance/gait change delay,
  pitch on braking, blind spots for negative obstacles/curbs, and Sport’s
  refusal/softening of body twists. Classical planners that assume DiffDrive
  kinematics understate these.
- Person floor (~1.2 m social zone in `SafetyEnvelope`) can bind at low speed
  even when ISO braking sum is smaller — keep human bucket **unscaled**.

---

## 7. Sidecar vs keep `grid_v1`

### Keep `grid_v1` when

- CI / headless city / nav-instruct need a **deterministic in-process**
  planner with zero ROS runtime.
- Failures are in grounding, semantics, termination, or localization — not
  L5/L6 local control (adjudication D1 gate).
- You need a sole motion consumer for GoalArbiter proposers
  ([`docs/INSTRUCTION_NAV_HILLCLIMB.md`](../../../../docs/INSTRUCTION_NAV_HILLCLIMB.md)).

### Stand up Nav2 sidecar when

- Phase-3 leashed field (or frozen BARN/dynamic suite) shows **dominant**
  oscillation, dynamic freeze, or curb-approach failures attributable to
  local control — adjudication’s named gate.
- You need SE2 / lattice feasibility that circular A* cannot express.
- You want an external **RPP baseline vs MPPI challenger** with Parcel still
  owning the final metric monitor and Sport I/O.

### Sidecar shape (recommended)

```text
Parcel TaskExecutive
  -> NavigateGoalV1 (frame, TTL, freshness)
  -> [optional] Nav2 Route Server / graph   # city topology later
  -> Smac2D baseline | Hybrid/Lattice challenger
  -> validated smoother (reject if SE2 footprint fails)
  -> RPP baseline | MPPI challenger
  -> exactly one velocity smoother
  -> Parcel fail-closed collision monitor (exact zero)
  -> ControlManager -> Unitree Sport
```

Do **not** let Nav2 Collision Monitor be the only gate; Parcel must still
enforce embodiment-specific stop envelopes and Sport stop confirmation.
Do **not** dual-smooth (Nav2 velocity smoother + Parcel S-curve) without an
explicit single-owner rule.

**Cost caution (still valid):** ROS 2 image pin, TF discipline, and MPPI
tuning compete with the voice→behavior differentiator. Sidecar is a parked
card until attribution demands it — or a time-boxed spike with kill criteria.

---

## 8. Top 5 recommendations

1. **Keep `grid_v1` as sole production writer; Nav2 is an exclusive challenger
   sidecar.** No v1 authority migration. Gate the spike on measured L5/L6
   dominance (adjudication D1) or a frozen dynamic/BARN A/B with kill
   criteria.

2. **Ship a Parcel fail-closed collision monitor after every smoother/shaper
   (Nav2 semantics, in-process first).** Stale/missing/malformed scan or
   transform → exact zero on physical profiles; forbid scan-missing stub
   translation outside labeled sim. Align with Nav2 `source_timeout` fail-closed
   default and audit P0.1/P0.2.

3. **Replace constant stop floors with a single measured envelope authority.**
   Unify `stop_distance_m` / `obstacle_stop_m` under
   `stop_distance(v) = r + vτ + v²/(2a_meas) + Zs + Zr`; recompute on every
   `max_vx` / decel change; commission Sport stop distance on the real gait
   surfaces. Mark current 0.8 m floor **UNVERIFIED** at cruise.

4. **Adopt RPP regulation patterns in Parcel now; use stock RPP as sidecar
   baseline before MPPI.** Curvature + obstacle speed scaling + arc collision
   check give an interpretable bisect path. Promote MPPI only as the dynamic
   challenger with non-negotiable hard critics and Sport-latency eval.

5. **When SE2 matters, challenge with Smac Hybrid-A* (then Lattice), not
   NavFn.** NavFn/Smac2D are circular-family peers of `grid_v1`. Hybrid-A*
   (Dubins/Reeds-Shepp + footprint) matches Nav2’s legged guidance; Lattice
   if Go2 needs a custom minimum control set. Always re-validate footprints
   after smoothing.

---

## 9. UNVERIFIED flag register

| ID | Claim | Why flagged | What would verify |
|---|---|---|---|
| U1 | Nav2 MPPI is “better” than Parcel local control | One/few BARN anecdotes; different footprint & stack | Frozen corpus A/B, same sensors/timeouts, Go2 or faithful dynamics |
| U2 | Smac Hybrid/Lattice 50–200 ms on Parcel compute | Upstream/demo figures | Timed planner_server on pinned Orin image under GPU load |
| U3 | `stop_distance_m: 0.8` safe at `max_vx≈0.9` | Constant floor vs `v²/2a`; Sport decel unknown | Instrumented stop tests per gait/surface; set `a_meas`, `τ_e2e` |
| U4 | Unitree “2 m” guidance is a nav stop envelope | Manual operate-at-a-distance text, not autonomy spec | OEM-pinned PDF + Parcel policy decision (social vs geometric) |
| U5 | Nav2 Collision Monitor alone makes Parcel fail-closed | Valuable filter, not cert; ordering/shaper bugs are local | Parcel post-shaper exact-zero tests + physical freshness faults |
| U6 | DiffDrive RPP/MPPI tracks Go2 Sport well enough | Kinematic model ≠ gait | Tracking-error and overshoot logs on EDU Go2 |
| U7 | CMU stack low-obstacle / delay numbers as Parcel gates | Ledger summary; commit may drift | Pin commit; reproduce notes; map to Parcel sensor mount |
| U8 | Lattice control sets for Go2 exist and are sane | Nav2 ships examples; Go2-specific set not commissioned | Generate/validate min control set on measured turn/stop limits |
| U9 | `Zs`/`Zr` = 0 is acceptable outdoors | Explicit temporary pins in `SafetyEnvelope` | Calibrate sensing intrusion + pose covariance on hardware |
| U10 | Hybrid-A* reverse/penalty defaults fit companion dog | Automotive-rooted defaults | Policy: disable/penalize reverse; prefer forward + rotate shim contextually |

---

## 10. Citation index

1. Nav2 Smac overview — https://docs.nav2.org/configuration/packages/configuring-smac-planner.html  
2. Nav2 Smac Lattice — https://docs.nav2.org/configuration/packages/smac/configuring-smac-lattice.html  
3. Nav2 NavFn — https://docs.nav2.org/configuration/packages/configuring-navfn.html  
4. Nav2 plugin selection — https://docs.nav2.org/setup_guides/algorithm/select_algorithm.html  
5. nav2_smac_planner README — https://github.com/ros-navigation/navigation2/blob/main/nav2_smac_planner/README.md  
6. Smac cost-aware paper — https://arxiv.org/html/2401.13078v2  
7. Dolgov Hybrid-A* — https://ai.stanford.edu/~ddolgov/papers/dolgov_gpp_stair08.pdf  
8. Nav2 RPP — https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html  
9. nav2_regulated_pure_pursuit_controller — https://github.com/ros-navigation/navigation2/tree/main/nav2_regulated_pure_pursuit_controller  
10. Nav2 MPPI — https://docs.nav2.org/configuration/packages/configuring-mppic.html  
11. nav2_mppi_controller — https://github.com/ros-navigation/navigation2/tree/main/nav2_mppi_controller  
12. Nav2 Collision Monitor — https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html  
13. Collision Monitor tutorial — https://docs.nav2.org/tutorials/docs/using_collision_monitor.html  
14. Collision Monitor watchdog PR — https://github.com/ros-navigation/navigation2/pull/3880  
15. Smac Lattice discourse — https://discourse.openrobotics.org/t/nav2-new-state-lattice-planner-beta/23143  
16. ROSCon Smac slides — http://download.ros.org/downloads/roscon/2022/On%20Use%20of%20Nav2%20Smac%20Planners.pdf  
17. CMU Go2 autonomy stack — https://github.com/jizhang-cmu/autonomy_stack_go2  
18. CMU development environment (primitives / waypoint vicinity) — https://www.cmu-exploration.com/development-environment  
19. Unitree Go2 manual (hosted) — https://physical-computing-lab.net/wp-content/uploads/Go2-User-Manual.pdf  
20. Parcel adjudication D1 — `scrum/20260805/task_1/ADJUDICATION.md`  
21. Parcel target architecture Nav2 sidecar — `scrum/20260807/task_2/TARGET_ARCHITECTURE.md`  
22. Parcel source ledger (classical row) — `scrum/20260807/task_2/SOURCE_LEDGER.md`  
23. Parcel `SafetyEnvelope` — `src/parcel_robot/authority.py`  
24. Parcel default nav safety — `configs/navigation/default.yaml`

---

## 11. Handoff notes for thesis synthesis

- N1 does **not** contradict keeping learned proposers above a classical writer;
  it insists the writer remain fail-closed and that Nav2 be optional.
- Safety/authority workstream (N5) should own exact-zero ordering; N1 supplies
  the Nav2 prior art for freshness fail-closed monitors.
- City/outdoor (N8) should prefer Route Server + keepout layers *conceptually*
  even if implementation stays in Parcel YAML graphs before ROS.
