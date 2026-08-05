# Day 21: Probability and Uncertainty for Robotics

## Mental model

Robot perception never hands you ground truth. Every useful quantity is a **belief**: a distribution over what might be true given noisy, delayed, partial observations. Senior SE instinct wants Boolean certainty (`owner_present = true`). Robotics wants statements like:

```text
P(owner at x | camera track, last pose, time since seen)
```

Uncertainty is not a bug in the sensors. It is the product. Covariance, confidence scores, and freshness budgets are how that product is shipped without lying to the planner.

Three ideas cover most of Module 3:

1. **Random variable** — a quantity whose value you do not know exactly (owner range, cell occupancy, body yaw).
2. **Belief update** — Bayes: prior × likelihood → posterior (often in log-odds for maps).
3. **Observability** — some state cannot be recovered from the sensors you have, no matter how clever the filter.

If a quantity is not observable, more filtering only invents a sharper wrong answer.

## Software-engineering analogy

Think of a eventually-consistent service with SLOs, not a CRUD row.

- A detector confidence is a **quality score on a read replica**, not a primary-key lookup.
- Covariance is a **structured error bar**: which dimensions are correlated and how wide.
- Innovation gating (Day 25) is **rejecting an outlier write** that fails schema/consistency checks.
- Treating `confidence=0.91` as Boolean true is like treating HTTP 200 as “money moved.”

You already budget for stale cache and partial failure. Probability is the same discipline with continuous state.

## Light equations

Bayes (scalar intuition):

```text
P(state | z) ∝ P(z | state) · P(state)
```

For binary occupancy of a grid cell, Parcel works in **log-odds** so updates stay additive and bounded:

```text
L = log( P(occupied) / P(free) )
L ← clip(L + hit_or_miss_update, L_min, L_max)
```

Gaussian 1-D belief (Kalman intuition for later days):

```text
mean μ, variance σ²
measurement z with variance R
K = σ² / (σ² + R)          # trust measurement more when prior is wide
μ' = μ + K (z − μ)
σ'² = (1 − K) σ²           # uncertainty shrinks only if the model is honest
```

Uncertainty propagation for independent errors (order-of-magnitude):

```text
var(a·x + b·y) = a² var(x) + b² var(y)
```

If you compose frames or integrate velocity, variances grow unless a measurement resets them.

## ASCII diagram

```text
  prior belief          observation z           posterior belief
  N(μ, σ²)      +       "owner @ 2.1 m"    ->   N(μ', σ'²)
       |                     |                        |
       |                     v                        v
  wide ellipse          likelihood peak         tighter (or rejected)
  "somewhere ahead"     from camera/LiDAR       if innovation too large

  Unobservable axis: σ stays huge no matter how often you update
```

## Map to Parcel / Go2

From `edu/INTRO.md` and `docs/NAVIGATION_CITY.md`:

- Camera tracks carry confidence; semantic goals require **two confidence-qualified observations** by default (`SemanticGoal.required_observations`, `minimum_confidence ≈ 0.55`) before treating a sidewalk/lamppost candidate as grounded.
- `grid_v1` stores **log-odds occupancy**, not Boolean walls. Hits and misses accumulate; cells clamp between configured min/max log-odds. Occupied for planning is a threshold on that belief, not a single ray.
- Unknown space is explicitly modeled: A* can admit unknown cells with a penalty (`unknown_cost`), while the controller only executes an **observed-clear** segment. That is uncertainty-aware planning, not “map is complete.”
- Owner follow prediction scales translation with predictor confidence; stale/invalid tracks fall back to measured owner rather than authorizing extrapolated motion (`follow.py` / `owner_prediction.py`).
- There is **no full probabilistic SLAM** on the production path today. Odometry drift (Day 24) remains a real uncertainty the stack does not yet close with loop closure.

**Codebase anchors (uncertainty basics):**

- `perception.PerceptionContract` — declares camera+LiDAR as the only allowed spatial sensors; maps stay a disabled `NullMapProvider` placeholder.
- `navigation/goals.py` → `SemanticGoal.minimum_confidence` / `required_observations` — semantic lock policy.
- `navigation/grid_planner.py` → `GridPlannerConfig.hit_log_odds` (0.90), `miss_log_odds` (0.45), `occupied_log_odds` (0.65), `unknown_cost` (2.5); `CellState` ∈ {UNKNOWN, FREE, OCCUPIED, OUT_OF_BOUNDS}.
- `navigation/owner_prediction.py` → `OwnerMotionPredictor` / `PredictedPath.confidence` — continuous belief used as a brake, not a Boolean.
- Product gate: `headless_city.HeadlessCityQualityHarness` runs the same observation types against city tasks.

Classify logged fields: measurement, estimate, or semantic belief — and always attach age.

## Failure story

A demo treated detector score `> 0.8` as “lamppost locked.” Under glare the score stayed high on a vertical sign edge while LiDAR showed free space through that bearing. The dog grounded a stand-off pose on the wrong object, A* routed cleanly in the rolling grid, and arrival fired because the semantic predicate still saw a high-confidence blob. Fix: require multi-observation agreement, freshness, and geometric consistency (range/bearing compatible with LiDAR free/occupied evidence) before terminal success — confidence alone is not a lock.

## Retrieval questions

1. Why is a confidence score closer to a cache quality metric than to a database primary-key hit?
2. In Parcel’s rolling grid, what does a log-odds update buy you that a Boolean “hit = occupied” map does not?
3. (From Day 13) If owner position is expressed in `base_link` but the goal is planned in `odom`, what must you transform — and what uncertainty travels with that transform?

## Optional 10-minute exercise

Open `docs/NAVIGATION_CITY.md` (sensor/map contract) and `src/parcel_robot/navigation/grid_planner.py` — read `GridPlannerConfig` defaults for `hit_log_odds`, `miss_log_odds`, `occupied_log_odds`, `unknown_cost`. Write one sentence each: (a) what a single hit does to belief, (b) what repeated misses do, (c) how unknown cost changes A* behavior without pretending unknown cells are free.
