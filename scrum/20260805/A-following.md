# Workstream A — anticipatory following + reacquisition

Why this is the sprint's core: a companion that trails your *past* position
feels like luggage; one that walks toward where you are *going* feels like it
is walking with you. And a follower with no recovery behavior fails the first
time you turn a corner — Parcel currently has **none** (backlog N6).

Research grounding: Follow-Bench's winning recipe is MPC tracking a
Kalman-predicted target; plain CV/CA suffices for a single-owner home
(learned predictors only pay off in crowds). RPF-Search-style reacquisition
reaches 97–100% vs 51% for the best baseline.

---

## W1 — `OwnerMotionPredictor` (pure module) · **Owner: Sol**

New `src/parcel_robot/navigation/owner_prediction.py` +
`tests/test_owner_prediction.py`. **Imports: numpy + stdlib only.** No Parcel
imports — Opus wires it in W2.

**Contract (frozen):**

```python
@dataclass(frozen=True)
class PredictedPath:
    horizon_s: float
    step_s: float                      # 0.1 — one point per control tick
    points: tuple[tuple[float, float], ...]   # world x,y; len == horizon/step
    speed_mps: float                   # current smoothed speed estimate
    heading_rad: float                 # current smoothed heading
    confidence: float                  # 0..1, from innovation consistency

class OwnerMotionPredictor:
    def __init__(self, *, horizon_s: float = 2.5, step_s: float = 0.1,
                 process_accel_std: float = 0.8): ...
    def observe(self, x: float, y: float, *, now_s: float,
                visible: bool = True) -> None: ...
    def predict(self, *, now_s: float) -> PredictedPath | None: ...
    def reset(self) -> None: ...
    @property
    def nis(self) -> float: ...        # normalized innovation squared (windowed)
```

Design points the tests must pin:
- Constant-velocity Kalman core with acceleration process noise; promote to
  CA only if CV innovation stays hot (or skip CA entirely if CV meets the
  acceptance — document the choice).
- Irregular observation intervals (owner track drops frames): `now_s` gaps up
  to 0.5 s must not destabilize the filter; >1.5 s without an observation →
  `predict` returns None (stale).
- `confidence` derives from windowed NIS: straight-line walking → high;
  direction change → dips then recovers within ~1 s of new observations.
- Non-finite inputs raise ValueError; `visible=False` observations update
  nothing but advance staleness.
- Determinism: same observation sequence → identical outputs.

**Acceptance tests:** straight-line owner at 1.2 m/s → 2.5 s prediction
endpoint within 0.15 m of truth; 90° turn → prediction curls toward the new
heading within 3 observations; teleport (tracking glitch) → NIS spikes and
confidence drops below 0.3; stale → None; performance: `observe`+`predict`
< 0.5 ms per call.

---

## W2 — Follow the prediction + uncertainty brake · **Owner: Opus** · after W1

Wire `OwnerMotionPredictor` into the follow path:

1. Feed it from the same owner-track observation point the
   `FollowOwnerController` uses today (one predictor instance owned by the
   runtime; reset on follow start/stop and owner-identity change).
2. `FollowOwnerController` servos a **lead point** on the predicted path
   (distance-parameterized: the point at `desired_distance_m` behind the
   predicted owner position at `lead_s ≈ 0.6 s`), falling back to today's
   direct/behind-formation behavior whenever `predict()` is None or
   confidence < threshold. The formation math stays; only the target it aims
   at changes. Config: `navigation.follow.prediction: {enabled, lead_s,
   min_confidence}` — fail-closed key validation (agreement 8).
3. **NIS uncertainty brake** as a *system-owned* rule, not a suggestion:
   when confidence dips (owner doing something unpredictable), scale the
   follow speed limit down (e.g. ×0.5 at confidence 0.3, floor at standstill)
   in the same place existing follow speed limits live. The brake must
   compose *under* the collision gate and arbiter, never replace them.
4. Snapshot: `follow.prediction` block (confidence, lead point, active/
   fallback) so the viewer and evals can see which mode is live.

**Acceptance:** unit tests for lead-point selection and fallback; the W9
turn-scenario shows reduced band error vs baseline; zero changes to
collision/arbiter authority (assert the diff touches neither).

---

## W7 — `SearchOwner` reacquisition skill · **Owner: Opus** · independent

Three-state deterministic skill, packaged like the existing semantic skills
(validator contract → adapter dispatch → verified completion):

1. **go_to_last_observed** — navigate to the last confident owner position
   (the predictor's last good state, W1, or raw track if W1 not landed),
   arrival radius ~0.5 m, using the existing grid navigator.
2. **sweep** — in-place yaw sweep (±120° at modest rate) watching for the
   owner track to reacquire; near-free on a quadruped.
3. **frontier_search** — bounded frontier exploration on the existing grid,
   candidates scored by information gain and pruned by a
   max-owner-velocity reachability disk from time-of-loss (default
   1.6 m/s · elapsed); give up cleanly after `max_search_s` (default 45 s)
   with a Vocalize (“I lost you — I’ll wait here”) and a Hold.

Wiring rules:
- Trigger: the **runtime** proposes SearchOwner when follow reports the owner
  lost beyond `lost_timeout_s` (default 3 s) — via the brain executive as a
  normal plan (deterministic trigger, no LLM in the loop), so interruption,
  invariants, and verified completion all apply. The owner reappearing at ANY
  state → immediate terminal success verified against the follow track
  (`owner_reacquired`, confidence-gated), and follow resumes.
- Completion is verified against controller/track feedback, never asserted
  (ReturnToSafePose is the template).
- All three states remain under the collision gate; frontier search respects
  `stop_on_stale_perception` like any navigation dispatch.

**Acceptance:** contract validation tests (unknown states impossible, timeout
bounds); adapter completion tests incl. reacquire-during-sweep and
give-up path; the W9 occlusion scenario reacquires within budget.

**Stretch (only if the sprint runs ahead):** Adap-RPF occlusion-aware
candidate scoring for behind-formation (published weights: occlusion 10,
distance 10, social 1, travel 1, stickiness 0.5) — roadmap §3 step 6.
