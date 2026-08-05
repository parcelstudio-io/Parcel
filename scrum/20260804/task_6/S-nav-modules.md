# Workstream S — Sol 5.6 Ultra: navigation eval + grounding pure modules

Rules as in task_4/task_5: new files only (`src/parcel_robot/instructnav/`
and `evals/nav_instruct/` pure parts), numpy/stdlib imports, injected
clocks/seeds, frozen signatures, tests in-card, ruff clean.

---

## N-S1 — Scenario spec + scoring · `src/parcel_robot/instructnav/scoring.py`

```python
@dataclass(frozen=True)
class GoalRegion:
    kind: str                       # "disc" | "polygon" | "relative_band"
    center: tuple[float, float] | None = None
    radius_m: float | None = None
    polygon: tuple[tuple[float, float], ...] | None = None
    anchor_entity: str | None = None   # for relative goals ("next to bench_1")
    band_m: tuple[float, float] | None = None   # (min,max) distance from anchor

    def contains(self, x: float, y: float,
                 anchor_xy: tuple[float, float] | None = None) -> bool: ...
    def distance_to(self, x: float, y: float,
                    anchor_xy: tuple[float, float] | None = None) -> float: ...

class FailureClass(str, Enum):
    GROUNDING_ERROR = "grounding_error"   # wrong/no entity resolved
    SEARCH_ERROR = "search_error"         # entity exists, never found
    PLANNING_ERROR = "planning_error"     # grounded, no/never-completing route
    CONTROL_ERROR = "control_error"       # route existed, execution failed/collided
    REFUSAL = "refusal"                   # dead-end reply, no attempt
    NONE = "none"

@dataclass(frozen=True)
class EpisodeScore:
    success: bool
    spl: float                    # shortest-path-length weighted success
    distance_to_goal_m: float
    time_to_goal_s: float | None
    failure: FailureClass
    detail: str

def score_episode(trace: Sequence[Mapping[str, object]], goal: GoalRegion,
                  *, shortest_path_m: float, max_time_s: float,
                  arrival_hold_s: float = 1.0) -> EpisodeScore: ...
```

Scoring rules pinned by tests: success = inside the region, stopped, and
holding for `arrival_hold_s` (agent-stop, not oracle-stop — the literature's
harder and honester convention); SPL uses the standard
`S · L/max(L, P)` form; `relative_band` regions score "next to the bench"
as distance-from-anchor within band AND not overlapping the anchor footprint.
Failure classification from trace fields (grounding events, search events,
route status, collision events, refusal reply) with an explicit precedence
order — one and only one class per failed episode.

## N-S2 — Semantic memory · `src/parcel_robot/instructnav/memory.py`

The "seen once, remembered" store the frustum-gated grounder lacks.

```python
@dataclass(frozen=True)
class RememberedEntity:
    entity_id: str
    label: str
    x: float; y: float
    last_seen_s: float
    confidence: float               # decays; refreshed on re-observation
    kind: str                       # "object" | "region"
    polygon: tuple[tuple[float, float], ...] | None = None

class SemanticMemory:
    def __init__(self, *, decay_half_life_s: float = 600.0,
                 min_confidence: float = 0.05, capacity: int = 256): ...
    def observe(self, entities: Sequence[Mapping[str, object]], *, now_s: float) -> None: ...
    def recall(self, label: str, *, now_s: float) -> tuple[RememberedEntity, ...]: ...
    def recall_all(self, *, now_s: float) -> tuple[RememberedEntity, ...]: ...
    def forget_region(self, x: float, y: float, radius_m: float, *, now_s: float) -> None: ...
    def snapshot(self) -> dict[str, object]: ...
```

Semantics pinned by tests: an entity observed once is recallable long after
it leaves the frustum, at decayed confidence; re-observation refreshes and
re-positions (objects can move); `forget_region` supports "I looked where I
remembered it and it's gone" (memory invalidation — without this, stale
memory poisons search); alias-insensitive label matching is the CALLER's
job (grounder), not memory's; capacity eviction drops lowest-confidence
first; deterministic under injected clock.

## N-S3 — Region + relation goal geometry · `src/parcel_robot/instructnav/relations.py`

```python
def nearest_point_in_region(polygon: Sequence[tuple[float, float]],
                            from_xy: tuple[float, float],
                            *, inset_m: float = 0.3) -> tuple[float, float]: ...

def next_to_placement(anchor_xy: tuple[float, float],
                      anchor_footprint_m: float,
                      from_xy: tuple[float, float],
                      *, band_m: tuple[float, float] = (0.4, 0.9),
                      facing_xy: tuple[float, float] | None = None,
                      occupied: Callable[[float, float], bool] | None = None
                      ) -> tuple[float, float, float] | None:  # x, y, heading
    ...

def towards_waypoint(target_xy: tuple[float, float],
                     from_xy: tuple[float, float],
                     *, stop_short_m: float = 1.2) -> tuple[float, float]: ...
```

`nearest_point_in_region`: "go to the sidewalk" = the nearest reachable
point *inside* the polygon, inset from the edge so the footprint fits —
never the polygon centroid (a centroid can be 20 m up the block; tests pin
this with an L-shaped region). `next_to_placement`: candidate ring in the
band, occupied-pruned, scored by approach distance and optional facing
preference; returns None when fully blocked (caller escalates). `towards`:
"walk towards X" = advance and stop short — motion toward, not arrival at
(the literature distinguishes these; tests pin stop-short).

## N-S4 — Episode generator · `evals/nav_instruct/generator.py`

Seeded generator producing episode specs for the matrix: instruction
template × entity placement (visible-at-start / behind-the-robot /
requires-search-behind-occluder) × distractors (second bench for ambiguity)
× start poses. Emits JSON episode files with the instruction text, world
placement overrides, `GoalRegion`, shortest-path length (computed on the
grid), and per-episode seed. Deterministic: same seed → byte-identical
episode set. Counts: ≥20 episodes per family × 3 difficulty tiers.
