# Workstream B — dynamic-obstacle awareness + companion-feel motion

Two complementary halves: the planner learns that people *move* (A* today
plans through where a pedestrian is about to be, leaving the reactive gate to
save it), and the velocity output learns to move like an animal instead of a
step function. Both are measured by evals that already exist.

---

## W3 — `DynamicAgentCostField` + rollout TTC (pure module) · **Owner: Sol**

New `src/parcel_robot/navigation/dynamic_costs.py` +
`tests/test_dynamic_costs.py`. **Imports: numpy + stdlib only.**

**Contract (frozen):**

```python
@dataclass(frozen=True)
class AgentTrack:
    x: float; y: float
    vx: float; vy: float               # world-frame velocity estimate
    radius_m: float = 0.35

def agent_cost_at(
    tracks: Sequence[AgentTrack],
    query_xy: np.ndarray,              # (N, 2) world points
    *,
    horizon_s: float = 2.0,
    step_s: float = 0.2,
    decay_half_life_s: float = 0.8,
    sigma_m: float = 0.45,
) -> np.ndarray:                       # (N,) costs in [0, 1]

def time_to_collision_s(
    tracks: Sequence[AgentTrack],
    *,
    robot_xy: tuple[float, float],
    robot_v: tuple[float, float],      # the CANDIDATE command, world frame
    robot_radius_m: float,
    horizon_s: float = 2.0,
) -> float:                            # inf when no predicted contact
```

Design points:
- `agent_cost_at`: for each track, project constant-velocity positions over
  the horizon; each projected position contributes a Gaussian lobe whose
  weight decays with lookahead time (half-life param). Sum, clip to [0,1].
  Vectorized: 8 tracks × 10 steps × 4,000 query points < 2 ms.
- `time_to_collision_s`: closed-form relative-motion solution per track
  (quadratic in t), not sampling; returns the earliest t in [0, horizon]
  where center distance ≤ radii sum.
- Edge cases pinned by tests: zero tracks (zero cost / inf TTC), stationary
  tracks (reduces to a static Gaussian), agent moving *away* (TTC inf),
  robot stationary while agent approaches (TTC finite — the check protects
  against being walked into, the *response* is the planner/gate's business),
  NaN velocity rejected.

---

## W4 — Wire dynamic costs into `grid_v1` + compile the TTC gate · **Owner: Opus** · after W3

1. **Cost merge:** in the grid planner's per-tick planning path, sample
   `agent_cost_at` over the candidate cells A* touches (or the local window —
   choose the cheaper integration and document it) and add a scaled penalty
   to traversal cost. Tracks come from the observation's dynamic agents +
   owner track (the owner gets a *reduced* weight — following someone should
   not read their own body as an obstacle wall; reuse the social-envelope
   distinction the runtime already makes). Config under
   `navigation.models.grid_v1.dynamic_agents:` with fail-closed keys.
   **Repeated A* at 10 Hz stays** — no D* Lite (adjudicated in the research;
   the grid is small enough).
2. **TTC gate:** in the same system-owned place the reactive-safety scaling
   lives, run `time_to_collision_s` on the outgoing command each tick;
   TTC below `brake_s` scales the command down progressively (never
   up), fully stopping below `stop_s`. This *supplements* the geometric
   gate — the unconditional last line of defense is untouched (working
   agreement 1; assert in tests that `collision.py`/`reactive_safety.py`
   are not modified).
3. Snapshot + viewer: expose `navigation.dynamic_cost_active` and the
   current min-TTC so the eval and HUD can see it working.

**Acceptance:** planner unit test where the straight-line path crosses a
crossing pedestrian's *future* corridor → chosen path detours behind them
while the static-only planner goes straight; TTC gate unit tests
(approaching/receding/crossing); W9 cut-in scenario zero hard collisions
with the reactive gate's intervention count *decreasing* vs baseline
(the planner now avoids what the gate used to catch).

---

## W5 — `SCurveVelocityShaper` (pure module) · **Owner: Sol**

New `src/parcel_robot/navigation/velocity_shaping.py` +
`tests/test_velocity_shaping.py`. **Imports: numpy/math + stdlib only.**

**Contract (frozen):**

```python
@dataclass(frozen=True)
class ShaperLimits:
    max_accel: float          # m/s^2 (or rad/s^2 for yaw)
    max_jerk: float           # m/s^3

class SCurveVelocityShaper:
    """Per-axis jerk-limited tracking of a target velocity."""
    def __init__(self, vx: ShaperLimits, vy: ShaperLimits, vyaw: ShaperLimits): ...
    def step(self, target: tuple[float, float, float], *, dt_s: float,
             emergency: bool = False) -> tuple[float, float, float]: ...
    def reset(self, current: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None: ...
    def scaled(self, factor: float) -> "SCurveVelocityShaper": ...  # affect modulation
```

Design points pinned by tests: continuous velocity AND acceleration across
target steps (that is the point); `emergency=True` bypasses jerk limiting
entirely and slews at `max_accel` toward zero — **an E-stop must never be
smoothed**; variable `dt_s` (the loop jitters) without overshoot;
`scaled(0.5)` halves both limits (calm mode); zero-cost when already at
target; step cost < 50 µs.

---

## W6 — Shaper into the dispatch path + affect modulation · **Owner: Opus** · after W5

1. Insert the shaper immediately before the SE2 HAL hand-off in
   `_dispatch_active` — *after* the collision gate and arbiter decide the
   command (safety sees the intent; the actuator sees the smooth version;
   the gate's stop decisions go through the `emergency` bypass, as does the
   E-stop path and the manager's zero-command stop path — enumerate every
   stop entry point and route each one, with a test per entry point).
2. Affect modulation: low-arousal affect state → `scaled(0.6)` profile;
   configured under `motion.shaping:` (enabled, limits, calm_scale),
   fail-closed keys. Default ON in sim.
3. Ledger: re-run the follow-bench suite; record RMS-jerk delta and confirm
   no follow-success or collision regression; provenance comments on any
   frozen numbers that legitimately move.

**Acceptance:** unit tests per stop-entry-point (E-stop, watchdog,
proximity stop, zero-target) proving none are smoothed; eval jerk drop
recorded in the ledger row.
