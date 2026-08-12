# RM-1 status — place-graph memory: ingestion, route query, persistence

Card: `scrum/20260811/task_2/SLAM_M_PLAN.md` (r2), Wave 1, RM-1.
Executor: Sol 5.6 Ultra. Date: 2026-08-12. **Not committed.**
Concurrent card: DR-1 on `pose.py` / `configs/navigation/pose.yaml` /
`tests/test_pose_drift_calibration.py` — untouched by this card (attribution
note at the bottom).

---

## 1. Frozen contract surface (what RM-2 consumes)

`parcel_robot.route_memory.place_graph` — new pure module. Re-exported from
`parcel_robot.route_memory`.

```python
class RoutePlaceGraph:
    def __init__(
        self,
        *,
        keyframe_spacing_m: float = DEFAULT_KEYFRAME_SPACING_M,        # 0.50 m
        max_contiguous_step_m: float = DEFAULT_MAX_CONTIGUOUS_STEP_M,  # 2.00 m
        attach_radius_m: float = DEFAULT_ATTACH_RADIUS_M,              # 8.05 m
        embed_fn: Callable[[Any], Sequence[float]] | None = None,      # stub default
    ) -> None: ...

    # ingestion
    def record_visit(
        self,
        pose: PoseEstimate,                       # MUST be Frame.MAP
        *,
        view_embedding: Sequence[float] | None = None,
        semantic_labels: Iterable[str] = (),
        timestamp_tick: int = 0,
        view_image: Any = None,                   # routed through embed_fn
        reanchored: bool = False,                 # authoritative jump signal
    ) -> RouteKeyframe | None                     # None = no new place admitted

    def reset_track(self) -> None                 # episode boundary; no fabricated edge

    # query
    def waypoints_toward(
        self, goal_xy: Sequence[float], from_xy: Sequence[float]
    ) -> tuple[RouteKeyframe, ...]                # () == fail-closed no route
    def nearest_index(self, xy, *, max_radius_m: float | None = None) -> int | None

    # persistence
    def save(self, path: Path | str) -> Path
    def load(self, path: Path | str) -> RoutePlaceGraph          # replaces self, atomically
    @classmethod
    def from_file(cls, path, *, embed_fn=None) -> RoutePlaceGraph
    def as_dict(self) -> dict[str, Any]
    def stats(self) -> dict[str, Any]

    # introspection
    frame -> Frame                 # always Frame.MAP
    keyframes -> tuple[RouteKeyframe, ...]
    edges -> tuple[PlaceEdge, ...]
    reanchor_events -> int
    keyframe_spacing_m / max_contiguous_step_m / attach_radius_m -> float
    __len__() -> int

@dataclass(frozen=True, slots=True)
class PlaceEdge:
    a: int; b: int; length_m: float
    crossed_reanchor: bool = False; traversals: int = 1
    key -> tuple[int, int]         # (a, b), a < b
    routable -> bool               # not crossed_reanchor
    as_dict() / from_mapping()

def stub_embed_image(image: Any) -> tuple[float, ...]   # default embed_fn

PLACE_GRAPH_SCHEMA = "parcel.route_memory.place_graph.v1"
DEFAULT_KEYFRAME_SPACING_M = 0.50
DEFAULT_MAX_CONTIGUOUS_STEP_M = 2.00
DEFAULT_ATTACH_RADIUS_M = 8.05
```

### The frozen-contract statement RM-2 consumes

> `RoutePlaceGraph.waypoints_toward(goal_xy, from_xy)` returns a tuple of
> `RouteKeyframe` in travel order, starting at the recorded keyframe the robot
> attaches to and ending at the recorded keyframe nearest the goal. **Every
> consecutive pair in the result is joined by an edge this graph actually
> recorded from observed motion and that was not laid across a MAP re-anchor
> jump.** No shortcut is ever synthesised. The empty tuple is the only failure
> value and it means "memory has no route" — never "maybe"; RM-2 must treat `()`
> as today's behaviour verbatim, fail-closed. Attachment on either end requires
> a recorded keyframe within `attach_radius_m` (8.05 m = half the rolling
> planner window), so the un-recorded legs at both ends always lie inside one
> window of live occupancy and remain the planner's problem, not memory's.
> A one-element tuple means the robot is already at the keyframe nearest the
> goal. **`SE2Goal` conversion is not in this module** — it stays in
> `proposer.py`, RM-2's. `record_visit` accepts `Frame.MAP` `PoseEstimate`s
> only, obtained through `parcel_robot.pose.observation_pose(obs, Frame.MAP)`;
> anything else raises. `reset_track()` must be called at every episode
> boundary, or the teleport from one episode's end pose to the next episode's
> start pose is recorded as a traversal.

---

## 2. Amendments made, with provenance

Every amendment is additive. Across `__init__.py`, `teach_repeat.py` and
`memory.py` there are **173 insertions and 1 deletion**, and the single deletion
is a one-line docstring replaced by an expanded one.

| file | amendment | provenance line |
|---|---|---|
| `route_memory/memory.py` | module docstring gains the RM-1 amendment block: why `RouteKeyframe` grew, why `ROUTE_MEMORY_SCHEMA` stays `v1` | "RM-1 amendment (2026-08-12, scrum/20260811/task_2/SLAM_M_PLAN.md card RM-1)" |
| `route_memory/memory.py` | `RouteKeyframe` gains `frame: str = "map"`, `labels: tuple[str, ...] = ()`, `tick: int = 0`, appended **after** `meta` so positional construction is unchanged; validated in `__post_init__`; persisted in `as_dict`; defaulted in `from_mapping` | "RM-1 additive fields — appended last so positional construction of the pre-existing signature keeps working" / "RM-1: frame discipline is persisted per keyframe, not inferred" / "RM-1: absent keys take the pre-amendment defaults" |
| `route_memory/memory.py` | `RouteKeyframe.xy` property (convenience, mirrors `PoseEstimate.xy`) | — |
| `route_memory/teach_repeat.py` | `_as_keyframe` re-embed branch now carries `frame`/`labels`/`tick` through the rebuild | "RM-1 amendment (SLAM_M_PLAN card RM-1): back-filling an embedding must not silently drop the keyframe's coordinate frame, labels, or tick" |
| `route_memory/place_graph.py` | **NEW** pure module (the card's deliverable) | module docstring cites the card |
| `route_memory/__init__.py` | re-exports the new module's surface; `PLACE_GRAPH_DOES_NOT_PROVE` folded into the package `DOES_NOT_PROVE`. Strictly additive: **0 removed lines** | see §6 (enumerated out-of-literal-OWNS note) |

`vpr.py` was in OWNS but needed no amendment: the `embed_fn` seam takes the
`embed_image(image)` shape directly and does not touch `VPREmbedder`.

### Why `RouteKeyframe` was extended rather than forked

The card is explicit: "RouteKeyframe is the store's existing type — build on it,
don't invent a parallel one." Stuffing frame/labels/tick into the existing
untyped `meta` mapping would have satisfied the letter and lost the point: the
frame is the gate, and a gate that lives in an unvalidated dict is not a gate.
All three are validated, all three are persisted, all three default to exactly
the pre-amendment behaviour.

### Frame vs frame_id

`RouteKeyframe.frame_id` (pre-existing) is the **rendered image** id that pairs
with `frame_bytes` on the VPR seam. `RouteKeyframe.frame` (RM-1) is the REP-105
**coordinate** frame, mirroring `RoutePath.frame`. The names are unfortunately
close; the distinction is spelled out in the class docstring and pinned by
`test_rm1_keyframe_amendment_still_reads_pre_amendment_payloads`.

---

## 3. Derived constants (no tuning to a gate)

| constant | value | derivation | source pinned by reference |
|---|---|---|---|
| `DEFAULT_KEYFRAME_SPACING_M` | 0.50 m | 5 grid cells. Two consecutive keyframes must be individually reachable as SE2 goals, so their arrival discs (radius `goal_tolerance_m` = 0.25 m) must not overlap: spacing >= 0.50 m = 5 cells at `resolution_m` = 0.10 m. Five is the **smallest** integer cell count satisfying it — at 4 cells the discs overlap. | live `GridPlannerConfig().resolution_m`, `.goal_tolerance_m` |
| `DEFAULT_MAX_CONTIGUOUS_STEP_M` | 2.00 m | 4 spacings. At `max_vx` = 1.0 m/s a 2.00 m single-sample displacement implies >= 2.0 s = 20 navigation ticks (`control_dt_s` = 0.1 s) of unobserved motion. For any caller sampling at or near the navigation tick that is a MAP discontinuity, not motion. | `configs/robot.yaml` `max_vx` parsed in the test |
| `DEFAULT_ATTACH_RADIUS_M` | 8.05 m | half the rolling planner window: `grid_size_cells * resolution_m / 2` = 161 * 0.10 / 2. Inside one window the planner has live occupancy for the un-recorded connecting legs; beyond it, attaching would be memory asserting reachability over ground no live map covers. | live `GridPlannerConfig().grid_size_cells`, `.resolution_m` |

`GRID_RESOLUTION_M` / `GRID_GOAL_TOLERANCE_M` / `GRID_SIZE_CELLS` /
`PLATFORM_MAX_VX_MPS` / `NAV_CONTROL_DT_S` are **mirrored**, not imported, so the
module keeps zero navigation imports; `test_derived_keyframe_spacing_pinned_by_reference`
and `test_derived_step_and_attach_radius_pinned_by_reference` assert each mirror
equals its live source, so a planner retune reddens the gate instead of leaving
the derivation quietly false.

---

## 4. MAP re-anchor contract (documented, tested)

* Keyframes are **MAP snapshots**. A later re-anchor does not retroactively move
  a recorded keyframe; there is no bundle adjustment here and none is planned.
* Edges are **traversal claims**. An edge laid across a jump is recorded (the
  history stays honest), flagged `crossed_reanchor=True`, and **excluded from
  routing** — routing over one would be precisely the invented shortcut the card
  forbids.
* Detection: `reanchored=True` from the caller is authoritative; absent that, a
  single sample displacing more than `max_contiguous_step_m` is treated as a
  discontinuity. The heuristic's error is **one-directional by construction** —
  a caller sampling too coarsely gets spurious flags, which costs routability
  (empty tuple) and never safety.
* `PoseHealth.LOST` is not admitted and breaks the track: MAP jumps on recovery.
* `load()` and `reset_track()` clear the track, so nothing is stitched between a
  loaded file's last keyframe (or a previous episode's end) and wherever the
  robot is now.

**Known limitation, stated rather than hidden:** the distance heuristic cannot
distinguish a genuine 2 m jump from 2 s of unsampled walking. RM-2 should pass
`reanchored=True` from the pose provider's own correction event where it can
(`map_correction`-enabled profiles), rather than relying on the backstop.

---

## 5. Gate evidence

### 5.1 Property tests and their seeded-failure proofs

Two independent layers of proof. **Layer 1** is in-test: each property has a
companion case that constructs the exact forbidden artefact and asserts the
shared checker rejects it. **Layer 2** is a mutation harness that seeds the
defect into `place_graph.py` itself and confirms the named test reddens.

Layer 1 — in-test seeded failures (`tests/test_p4_place_graph.py`, 37 tests):

| gate item | property test | seeded-failure proof |
|---|---|---|
| no invented edges | `test_waypoints_toward_never_invents_a_straight_line_shortcut` — U-corridor, 10 m across / 30 m around; answer is 30.0 m through both corners | `test_seeded_straight_line_shortcut_is_rejected` feeds the 2-element (start, goal) chain a proximity-router would emit to the same checker: `pytest.raises(AssertionError, match="invented shortcut")`. Plus `test_seeded_near_miss_shortcut_is_rejected` — two nodes 0.6 m apart, never walked between, rejected by both the checker and the router. |
| fail-closed no-route | `test_disconnected_components_return_empty_tuple` | `test_seeded_control_same_visits_without_the_track_break_do_route` — identical geometry and sampling, connector actually walked, route exists. The emptiness is caused by the missing edge, not by a router that never answers. |
| fail-closed attach | `test_attach_radius_fails_closed_beyond_the_planner_window` | in-test control: a goal just inside the window routes. |
| persistence round-trip | `test_persistence_round_trip_is_byte_exact` — save/load/save byte-identical, keyframes/edges/params equal, query identical | `test_load_refuses_corrupt_files_without_partially_loading` — 6 seeded corruptions (bad schema, missing `keyframes`, dangling edge index, duplicate edge, negative spacing, truncated keyframe) + malformed JSON + missing file; each refuses, and after **every** refusal the live graph's keyframes, edges and re-serialised bytes are unchanged. Closed with a control: the good file still loads. |
| MAP frame in schema | `test_map_frame_recorded_in_persisted_schema` — `frame == "map"` at graph level **and** on every keyframe | `test_record_visit_refuses_odom_frame`, `test_load_refuses_a_graph_claiming_another_frame` (container lies; keyframe lies) |
| derived spacing pinned by reference | `test_derived_keyframe_spacing_pinned_by_reference` | the "one cell finer overlaps" assertion — a wrong `KEYFRAME_SPACING_CELLS` reddens from either direction |
| determinism | `test_same_visits_give_the_same_graph_and_the_same_route` — equal dicts, equal bytes, equal routes, stable across repeats; `test_equal_cost_ties_break_deterministically` on a square loop | `test_seeded_determinism_check_has_discriminating_power` — a different visit order serialises differently, so the equality assertion is not blind |
| re-anchor jump | `test_reanchor_jump_flags_the_edge_and_blocks_routing` | `test_seeded_control_contiguous_sampling_of_the_same_geometry_routes` — same endpoints walked instead of jumped, routes fine |
| no onnx in the pure module | `test_place_graph_imports_no_onnx_torch_or_navigation` — AST walk of every `Import`/`ImportFrom`; forbids onnx/onnxruntime/torch/numpy/siglip and the navigation/runtime/instructnav packages; requires `parcel_robot.pose` | — |

Layer 2 — seeded implementation defects (harness in scratch; not committed):

```
mutation                               verdict   test that caught it
M1-jump-edges-routable                 KILLED    test_reanchor_jump_flags_the_edge_and_blocks_routing
M2-unbounded-attach                    KILLED    test_attach_radius_fails_closed_beyond_the_planner_window
M3-invent-straight-line-shortcut       KILLED    test_waypoints_toward_never_invents_a_straight_line_shortcut
M4-partial-load                        KILLED    test_load_refuses_corrupt_files_without_partially_loading
M5-spacing-not-derived                 KILLED    test_derived_keyframe_spacing_pinned_by_reference
M6-frame-not-persisted                 KILLED    test_map_frame_recorded_in_persisted_schema
M7-accept-odom-poses                   KILLED    test_record_visit_refuses_odom_frame
M8-nondeterministic-serialisation      KILLED    test_same_visits_give_the_same_graph_and_the_same_route
8/8 killed. place_graph.py restored byte-identical; baseline re-check GREEN.
```

M3 is the load-bearing one: it injects a direct `src -> dst` adjacency entry
into the Dijkstra frontier — the literal "invent the straight line" bug — and
the no-invented-edges test catches it.

### 5.2 Amendment tests in the pinned contract file

`tests/test_p4_route_memory.py` grew 4 cases, each citing its amendment:

* `test_rm1_keyframe_fields_default_to_pre_amendment_behaviour` — positional
  construction unchanged, defaults are the old shape, dict round-trip.
* `test_rm1_keyframe_amendment_still_reads_pre_amendment_payloads` — a v1
  payload written before the amendment loads unchanged; `frame_id` stays
  distinct from `frame`.
* `test_rm1_keyframe_amendment_validates_the_new_fields` — empty frame, list
  labels, float tick, negative tick all refuse.
* `test_rm1_teach_reembed_preserves_frame_labels_and_tick` — the re-embed branch
  in `teach_repeat.py` that silently dropped the three fields before the
  amendment.

All 14 pre-existing tests pass untouched.

### 5.3 ci_gate

Fresh **baseline** before any edit (2026-08-12T04:29:53Z), verified rather than
assumed: `RESULT: PASS`, default-suite `3668 passed, 9 skipped, 36 deselected`,
ruff `7 violation(s), baseline 7, new 0`. Matches the plan's stated baseline.

Post-RM-1 (2026-08-12T04:46:57Z): **`RESULT: PASS — every hard gate green`**,
default-suite `3778 passed, 9 skipped, 36 deselected`, all 10 hard gates PASS,
elapsed 134.6 s. Ruff `7 violation(s), baseline 7, new 0`.

Suite delta accounting for +110: RM-1 contributes **+41**
(`tests/test_p4_place_graph.py` 37 new, `tests/test_p4_route_memory.py`
16 -> 20). The remaining +69 are DR-1's concurrent Wave-1 additions to
`tests/test_pose_drift_calibration.py` and friends — not RM-1's, and green.

Ruff: repo-wide unique `(file, rule)` fingerprints = **7**, byte-identical to
`scripts/ci_ruff_baseline.json`. Zero new fingerprints from RM-1. (Four new
fingerprints appeared mid-work — `I001` x2, `RUF046`, `RUF007` — and were fixed,
not baselined.)

---

## 6. OWNS compliance

Touched, all inside OWNS:

* `src/parcel_robot/route_memory/memory.py` (amendment, provenance above)
* `src/parcel_robot/route_memory/teach_repeat.py` (amendment, provenance above)
* `src/parcel_robot/route_memory/place_graph.py` (NEW pure file in the package)
* `tests/test_p4_route_memory.py` (amendment-citing cases)
* `tests/test_p4_place_graph.py` (NEW)
* `scrum/20260811/task_2/RM1_STATUS.md` (this file)

**Enumerated note — `src/parcel_robot/route_memory/__init__.py`.** Not named
literally in either OWNS or MUST-NOT-TOUCH. Edited to re-export the new module,
which is the completion of "NEW pure files in the package": RM-2's
`from parcel_robot.route_memory import RoutePlaceGraph` needs it. The edit is
strictly additive — `git diff` shows **0 removed lines** — appends names to the
import block, `DOES_NOT_PROVE` and `__all__`, and alters no existing export.
Flagged here rather than left for the audit to discover.

Not touched: `route_memory/proposer.py`, `route_memory/runtime_hook.py`,
`route_memory/citywalker.py`, `route_memory/vlfm.py`, `route_memory/vpr.py`,
`runtime.py`, `navigation/pipeline.py`, `evals/**`, `pose.py`.

**DR-1 attribution.** `git diff --name-only` shows `src/parcel_robot/pose.py`,
`configs/navigation/pose.yaml` and `tests/test_pose_drift_calibration.py` as
modified. Those were **not** in the working tree at RM-1 start (verified against
the `git status --porcelain` snapshot taken before the first edit, which listed
neither) and are DR-1's concurrent Wave-1 card. RM-1 imports `Frame`,
`PoseEstimate` and `PoseHealth` from `pose.py` read-only; any red in those three
files is DR-1's.

---

## 7. does_not_prove

* `RoutePlaceGraph` does not prove SLAM, loop-closure correctness under real
  localization, VPR recall, or that a recorded edge is still traversable now.
  The graph is a history, not a map: an edge records that the robot walked there
  once, and nothing in this module re-checks that the corridor is still open.
  The reactive gate and grid_v1 remain the sole motion authority and are what
  actually keeps the robot from walking into a newly-placed obstacle on a
  remembered edge.
* The default `embed_fn` is `stub_embed_image`, a deterministic hash stand-in.
  Nothing here proves SigLIP2 place recognition; the seam is wired and unproven.
* Zero product consumers as of RM-1. Nothing in this card puts a waypoint on the
  motion path — that is RM-2, behind a default-OFF flag.
* Cross-session persistence: the **mechanism** lands here. Whether a graph is
  reloaded across sessions, where it is stored, and for how long remain
  owner-gated OPEN items in SLAM_M_PLAN.
* The re-anchor distance heuristic is cadence-dependent (see §4).
