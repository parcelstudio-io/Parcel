# Day 25: State Estimation and Sensor Fusion

## Mental model

Fusion is a **predict → update** loop. Predict with a motion model (odometry/IMU). Update when an observation arrives (LiDAR hit, owner track, semantic re-sight). The estimate is always a compromise between model trust and measurement trust.

```text
prior belief  --predict(Δt)-->  predicted belief
predicted     --update(z)---->  posterior belief
```

Complementary filters blend high-pass / low-pass channels (classic: gyro for fast angles, accelerometer for slow gravity reference). Kalman / EKF formalize the same idea with covariances. **Innovation gating** rejects measurements that are too surprising given current uncertainty — better a missed update than corrupting the state.

Stale state is not fused state: if the stamp is old, you are predicting without admitting it.

## Software-engineering analogy

Fusion resembles **multi-source reconciliation with conflict resolution**:

- Predict = apply the event log forward.
- Update = merge a read replica with a version vector (timestamp + covariance).
- Gating = reject a write that fails CAS / invariant checks.
- Publishing a point estimate without freshness is returning a cache entry with no `Age` header.

Parcel already does lightweight versions of this for owner motion and occupancy log-odds; it does not yet run a full robot EKF for global pose.

## Light equations

Kalman gain intuition (scalar):

```text
innovation  ν = z − H μ_pred
K = P Hᵀ (H P Hᵀ + R)⁻¹
μ ← μ_pred + K ν
```

If `|ν|` is huge versus its predicted std, **gate**: skip or inflate R. Owner predictor in Parcel tracks NIS (normalized innovation squared) over a window for confidence.

Complementary filter (attitude sketch):

```text
θ ← α (θ + ω Δt) + (1 − α) θ_accel
```

High α trusts integration short-term; low α pulls toward the slow absolute reference.

## ASCII diagram

```text
  IMU / odom ---- predict ----+
                              v
                         state μ, P
                              ^
  camera track --gate?--+     |
  LiDAR geometry -------+--> update

  stale z: do not update; maybe widen P or brake
```

## Map to Parcel / Go2

- `OwnerMotionPredictor` (`navigation/owner_prediction.py`) is a small **CV Kalman filter** with acceleration process noise, stale timeout `_STALE_S = 1.5`, and windowed NIS → `PredictedPath.confidence`. `FollowPredictionConfig` uses that confidence to scale or stop translation (`lead_s` default 0.6 s).
- Occupancy fusion is Bayesian log-odds in `RollingOccupancyGrid.update`, not an EKF — still predict-free evidence accumulation with clamps.
- Dynamic agents: constant-velocity rollout costs in `dynamic_costs.agent_cost_at`, wired by `dynamic_layer.tracks_from_payload` — prediction without full interactive multi-agent filtering.
- Docs: no global pose fusion / SLAM. Semantic tracks arrive pre-associated from the adapter; hardware re-ID fusion is future work.

**Codebase anchors (fusion):**

- `owner_prediction.OwnerMotionPredictor` / `PredictedPath`
- `follow.FollowPredictionConfig.min_confidence`, `brake_full_confidence`, `brake_stop_confidence`
- `grid_planner.RollingOccupancyGrid.update` / `GridPlannerConfig` hit/miss log-odds
- `dynamic_layer.merged_cost_mask`, `time_to_collision_verdict`
- `GridNavigator._sensor_frame_is_fresh` — refuse map updates on unsynchronised stamps (safe-valley profiles)
- Contract: `docs/NAVIGATION_CITY.md` “Owner following and reacquisition”

## Tick-by-tick in Parcel

Three fusion styles coexist without being one mega-EKF:

1. Body pose: trust vendor/sim odometry (open problem for drift).
2. Occupancy: independent per-cell log-odds updates from LiDAR.
3. Owner: CV Kalman in `OwnerMotionPredictor` with NIS-based confidence braking in follow.

Do not “average” camera range and LiDAR range in the LLM. If you fuse ranges, do it in typed geometry code with stamps. Innovation gating belongs next to the filter, not in prompt text. Stale extras (`lidar_fresh`, `odometry_fresh`) are first-class fusion inputs on profiles that honor them.

## Failure story

Follow enabled lead-point prediction while confidence stayed high during a sharp owner turn (CV model lag). The dog cut the corner through a soft dynamic lobe that A* treated as a mild penalty, not a wall, and the reactive gate stopped late. Root cause: fusion trusted prediction without enough innovation penalty on turn onset. Fix already foreshadowed in code: confidence brake + fall back to measured owner when tracks are stale/invalid — keep prediction advisory, not authoritative.

## Design rule for Parcel fusion

Prefer many small, inspectable estimators over one opaque mega-filter at the brain layer. Occupancy cells, owner CV filter, and soft agent rollouts can disagree; arbitration and safety gates exist for that reason. When adding a new sensor, write: state represented, predict model, update model, gate, stale behavior, and which layer consumes the estimate. If you cannot fill that table, you are not ready to couple it to `vx`.

## SE analogy add-on: leases and TTLs

Treat every fused estimate as a **leased cache entry**. `PredictedPath.confidence` and `_STALE_S` are the lease. When the lease expires, consumers must degrade (measured owner only, or stop translating) rather than extend the lease by hope. The same pattern applies to semantic candidates: `required_observations` is a quorum; one lucky frame is insufficient. Production robotics is mostly lease discipline at physical timescales.

## Retrieval questions

1. What is the difference between predicting with odometry and updating with a LiDAR/owner measurement?
2. How does Parcel turn `OwnerMotionPredictor` confidence into safer follow motion?
3. (From Day 21) Why can gating a high-confidence but geometrically inconsistent measurement improve safety?

## Optional 10-minute exercise

Open `src/parcel_robot/navigation/owner_prediction.py` (`OwnerMotionPredictor`) and `FollowPredictionConfig` in `follow.py`. Trace one path: low NIS confidence → scaled `vx`. Note the stale path when observations stop.
