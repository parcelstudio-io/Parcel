# Task 19 — DOOR-1: through a doorway, and a follow standoff that obeys config

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** P1-E's two escalations
(`task_12/P1E_STATUS.md`): (1) `safety.obstacle_stop_m: 0.65` makes the
reactive gate refuse any corridor narrower than ~1.19 m, so the prototype
cannot pass a standard doorway (0.8–0.9 m) — an OBSTACLE number, not a
person one; (2) `FollowConfig.desired_distance_m` is an import-time constant
(`follow.py`), so the follow controller still stands off at 1.85 m whatever
the overlay says — P1-E pinned it as an assertion and handed off a one-line
fix with its blast radius.

## Why
P1-E made the social zone a config and proved the dog can approach to 0.7 m
— and then the next wall is literal: an apartment is doorways. The audit (§6)
already named the planner/gate envelope disagreement; this card closes the
indoor-geometry half of it.

## Work
1. **Obstacle envelope from config with a floor,** exactly the P1-E pattern:
   `safety.obstacle_stop_m` derived through `SafetyEnvelope` with a named
   floor at the commissioning band (derive it from `stop_distance(cruise)` +
   footprint the way P1-E derived the social floor, and say why); planner
   inflation from the same quantity. Overlay lands the indoor value
   (pre-register it from the doorway arithmetic: a 0.8 m doorway must be
   traversable with the Go2's 0.32 m footprint and the measured stop
   distance).
2. **Follow standoff obeys config:** `FollowConfig.desired_distance_m` from
   the envelope at construction, not import; `owner_follow.owner_keepout_m`
   and the social zone agree by construction (one number, P1-E's rule).
3. **Measure it where it bites:** a dev-scene corridor cell at 0.8 m and
   0.9 m width (add the geometry to the dev scene ONLY if it can be done as
   `vis_*`-safe physics-equivalent additions — otherwise a scratch scene
   variant, never the frozen one); pre-register traversal with zero
   robot-initiated contact and the gate's stop behaviour when a person
   stands in the doorway.
4. Seeds RED: obstacle floor removed; planner decoupled; follow distance
   silently constant again.

OWNS: `authority.py` obstacle-envelope derivation, `navigation/reactive_safety.py`
obstacle-distance SOURCE only (semantics untouched; AST ratchet regenerated
with a log entry if `__post_init__` moves again), `navigation/grid_planner.py`
inflation, `follow.py` construction-time config, `configs/robot.prototype.yaml`
safety/follow blocks, `tests/test_door1_*.py`, `task_19/` docs. MUST NOT
TOUCH: `core/hard_stop`, e-stop latch, TTL/watchdog, `SafetySupervisor.validate`,
the frozen `city_block.xml` digest.

## Definition of done
Both corridor widths traversed with zero contact and the person-in-doorway
stop measured; follow standoff equals the overlay value; seeds RED;
`DOOR1_STATUS.md` with the semantics-diff-empty evidence.
