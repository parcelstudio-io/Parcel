# Day 22: Camera Fundamentals

## Mental model

A camera does **not** measure 3-D points. It measures brightness (and color) on a 2-D sensor after a projective transform. Depth along each ray is fundamentally ambiguous from a single image: infinitely many 3-D points project to the same pixel.

```text
3-D world point  --project-->  2-D pixel
pixel alone      -/->          unique metric range
```

Everything “vision” does for Parcel — detect owner, find sidewalk, re-identify after occlusion — is inference layered on that projection. Metric navigation still needs range (LiDAR, stereo/depth, or a known size prior) and calibrated extrinsics into the robot frames you already studied.

## Software-engineering analogy

An image is a **lossy, viewpoint-dependent serialization** of the scene — like rendering a 3-D scene graph to a PNG and then trying to recover object poses from the PNG.

- Intrinsics are the **codec parameters** (focal length, principal point, distortion).
- Extrinsics are the **mount pose** of the camera in `base_link` (a fixed SE(3)/SE(2) edge in the TF graph).
- A detector box is a **parsed span with a confidence**, not a database row for “the owner.”
- Re-identification is **session resume after the TCP connection dropped** — same logical entity, new evidence.

Never let a language model invent pixel→metre math. Calibration and projection belong in deterministic geometry code.

## Light equations

Pinhole projection (idealized):

```text
x = f_x * (X / Z) + c_x
y = f_y * (Y / Z) + c_y
```

`(X,Y,Z)` in the camera frame; `(x,y)` in pixels. `Z` (depth) divides — that is the ambiguity. Distortion models bend rays near the edges; uncorrected edges poison bearing estimates.

Bearing from a detection (rough planar nav intuition):

```text
bearing ≈ atan2( (u - c_x) / f_x , 1 )   # horizontal angle in camera frame
```

Without depth, you get a ray, not a point. Parcel’s city stack therefore expects **typed semantic tracks** that already carry range/bearing (or simulator-oracle equivalents), not raw pixels in the planner.

## ASCII diagram

```text
         world point P
              *
             /|
            / |
           /  | Z (unknown from one pixel)
          /   |
    camera ----+---- image plane
         \    |
          \   v
           \ pixel p = project(P)

    Many P' along the ray share the same p
```

## Map to Parcel / Go2

From `edu/INTRO.md` and `docs/NAVIGATION_CITY.md`:

- Product split: **camera = appearance / people / owner / semantics**; **LiDAR = metric free space**. Complementarity is intentional: “looks like the owner” vs “2.1 m away.”
- Runtime path: `Dog.navigate` / `DirectiveNavigator` consumes **bounded camera/depth semantic tracks**, not a live detector inside `grid_v1`. Tracks are an adapter boundary.
- Honesty check: today’s simulator emits typed tracks from known scene objects with range/FOV filtering. There is **no pixel detector, depth estimator, occlusion-aware semantic camera, or re-identification model** on the hardware path yet. Architecture is ready; perception realism is not.
- Semantic search (`navigation/search.py`) rotates in place and requires repeated confidence-qualified observations before grounding unknown goals (sidewalk, lamppost).
- Owner follow (`follow.py`) and `SearchOwner` reacquisition use owner visibility/confidence; loss triggers bounded search phases, not infinite wandering.
- Frames matter: detections live in `camera`; goals and A* live in `odom`/map-local frames. Extrinsics and stamps must align or bearings silently point at the wrong world.

**Codebase anchors (camera / semantics):**

- `perception.PerceptionContract.camera_role` = `"owner/object/scene perception"`; `lidar_role` stays range/free-space. `ALLOWED_SPATIAL_SENSORS = {camera, lidar}`.
- `navigation/semantic_map.py` → `SemanticCandidate`, `ObservationSemanticMap.query(SemanticGoal, …)`, `semantic_candidates_from_observation`.
- `navigation/search.py` → rotate-in-place search returning `MidLevelCommand(..., note="semantic_search_scan")`.
- `navigation/pipeline.py` → `DirectiveNavigator` mission states through semantic resolution / verification.
- Optional recovery path: soft imports from `instructnav.grounding.resolve_grounding` / `SemanticMemory` when `instructnav_recovery` is enabled.
- Eval: `tests/test_headless_city_tasks.py` + `HeadlessCityWorld` exercise sidewalk/lamppost directives against typed tracks.

## Tick-by-tick in Parcel

On an unknown object goal, `DirectiveNavigator` stays in semantic resolution until `search.py` has accumulated `SemanticGoal.required_observations` confidence-qualified hits from `ObservationSemanticMap`. Only then does `safe_approach_pose` emit a `GoalPose` for `GridNavigator`. Camera never writes occupancy cells; it only proposes *which* metric goal geometry should become true. If tracks disappear mid-approach, verification fails closed (`semantic_arrival_verification_failed`) rather than celebrating the last planned waypoint.

For owner identity, `FollowOwnerController` consumes the camera owner track in the odometry frame. There is no Parcel pixel pipeline in-tree yet — the adapter boundary is the teaching point: keep detectors swappable, keep geometry deterministic.

## Failure story

An early follow prototype converted bbox center-x to a yaw rate with a hand-tuned gain and ignored depth. When the owner raised an arm, the bbox widened and the center jumped; the dog yawed into a curb while believing it was “centering the owner.” LiDAR proximity eventually brake-stopped the motion. Fix direction: treat vision as identity + bearing hypothesis; fuse or gate with metric range; never let bbox width jitter become lateral velocity without a geometric model and freshness check.

## Retrieval questions

1. Why can a single camera image not uniquely determine how far the owner is?
2. What does Parcel currently pass into navigation instead of raw images, and why is that adapter useful even when the simulator cheats?
3. (From Day 14) If camera extrinsics are stored as roll-pitch-yaw and you apply them in the wrong order, what class of bug appears in owner bearing?

## Optional 10-minute exercise

Open `docs/NAVIGATION_CITY.md` (sensor/map contract) and `src/parcel_robot/navigation/semantic_map.py` (`SemanticCandidate`, `ObservationSemanticMap`). Sketch the path for “go near the lamppost”: directive → `SemanticGoal` → `search.py` observations → `approach.safe_approach_pose` → `grid_v1`. Mark appearance vs metric vs simulator-oracle steps.
