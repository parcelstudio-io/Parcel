"""Card C3 (STALL-CLASS-1) — the progress watchdog's rules, and WHY a stall happened.

``DirectiveNavigator._progress_watchdog`` used to answer one question ("has the
range to the goal stopped falling?") and take one action ("re-ground and try
again"). NAV-GEN-1 measured what that costs: 68 of 157 strict failures on
generated scenes end ``navigation_no_progress``, and on the 26 that are not the
POI second-oracle defect **every single one** ends the same way — the global
planner still reporting ``status=planned``, the body having travelled 0.00-0.02 m
over the whole 200-tick window, and the mission having spent all three of its
commitments re-deriving the byte-identical plan for the byte-identical instance.

The measured taxonomy (NAV-GEN-1 A0, commissioned arm, generated block; the
per-class rows are in ``scrum/20260829/task_2/C3_STATUS.md`` §1):

* **17/26 — the navigator's own brake holds the body AT the ring.** The shipped
  ``configs/navigation/default.yaml`` ``safety.predictive_mode`` is
  ``projected_speed_cap``, whose allowed closing speed is
  ``(range - obstacle_stop_m) / reaction_time``: it reaches zero *at* the ring
  and therefore parks the body at exactly ``0.8000`` m without ever crossing it.
  Every one of those 17 episodes sat at 0.8000 m for 199 of 200 ticks with the
  brake reporting ``obstacle_projected_speed_cap``. Card A2's release authority
  (:meth:`~parcel_robot.navigation.pipeline.DirectiveNavigator._gate_blocked_route_recovery`)
  is exactly the right answer to that state, but its witness is the single
  string ``obstacle_stop``, so ``_steps_gate_blocked`` stayed 0 for the entire
  hold and the release never fired.
* **5/26 — the runtime's final gate refuses what the navigator's brake passed.**
  ``_control_observation`` deliberately drops the *relational target's own*
  LiDAR returns so the point controller may reach its stand-off pose; the
  runtime brake (documented in that method as seeing "the unmodified sensor
  view") does not. Measured: the raw nearest return is the target's own body at
  0.68-0.73 m while the navigator's brake is handed 1.60-1.96 m, so the
  navigator commands cruise, reads ``clear``, and is stopped dead every tick.
* **4/26 — the robot is yielding to its OWNER.** ``apply_reactive_safety``
  treats the visible owner as a person (clearance 1.07-1.23 m against a
  predictive person stop of 1.302 m); the watchdog's own person-yield clause
  reads ``nearest_person_m``, which the owner is not on, so 20 s of correct
  social yielding is scored as a navigation stall.

Three different authorities, one shape: **the body is held with a route still
planned, and the navigator cannot see the refusal.** So the classification here
is deliberately made from what the *body* and the *planner* say, not from any
gate's spelling: no brake note, no policy value, no floor. Nothing in this
module can move what ``apply_collision_brake`` or ``apply_reactive_safety``
enforce — it decides only which door an already-fired watchdog walks through.

Leaf by construction (card DEC-0: ``pipeline.py`` is over the ceiling): pure
functions and constants, no imports from ``pipeline``, no state.
"""

from __future__ import annotations

from typing import Final

#: Improvement in range-to-goal that counts as progress, in metres.
#:
#: Hysteresis, not a threshold on speed: a semantic goal is re-estimated from a
#: noisy detector every tick, so without a dead band the running minimum
#: ratchets down on jitter alone and a fully stopped robot reports progress
#: forever (NAV-CORE measured that failure on ``_steps_gate_blocked``).
PROGRESS_HYSTERESIS_M: Final = 0.025

#: ``RoutePlan.status`` values that mean "the global planner still has a route"
#: (``navigation/grid_planner.py`` ``RouteStatus``). ``at_goal`` is excluded
#: because it is an arrival, not a route; ``goal_blocked`` / ``no_path`` are the
#: planner's own proof that there is nothing to execute, and those already have
#: their own release authority in ``_unroutable_goal_recovery``.
ROUTED_STATUSES: Final = frozenset({"planned", "partial"})

#: ``Mission.metadata`` key carrying the class of the stall that fired.
STALL_CLASS_KEY: Final = "stall_class"

#: ``Mission.metadata`` key counting :data:`HELD_WITH_ROUTE` stalls so far.
HELD_STALLS_KEY: Final = "held_stalls"

#: The navigation-config key (``progress_watchdog.held_stall_release``) and the
#: ``DirectiveNavigator`` kwarg that arm the release door. **Default OFF, and
#: OFF on the shipped profile**, because card F1's verifier measured that arming
#: it moves frozen hard-safety evidence: on the committed C0 mutation panel the
#: ``region_goal-D-15`` verdict moves ``authority_disagreement`` ->
#: ``tolerated_boundary``, so the panel no longer reproduces. Arming it on the
#: shipped profile is an owner re-freeze decision, not a code change.
HELD_RELEASE_FLAG: Final = "held_stall_release"

#: How many held stalls this mission must survive before the commitment itself
#: is released. **Not a tuning knob — a measured floor of 2.**
#:
#: The first held stall gets the ordinary re-ground, exactly as before C3: the
#: world may simply have changed under a stale plan, and NAV-GEN-1 measured the
#: cost of skipping that grace — releasing on the FIRST held stall turned four
#: episodes that reach the goal today (``gen:880011:bench:1``,
#: ``gen:880016:crosswalk:0``, ``gen:880024:bench:0``, ``gen:880025:crosswalk:2``)
#: into ``semantic_target_unreachable``, because a mission that merely paused on
#: its way to a reachable target had the target struck off permanently. Only a
#: held stall that SURVIVES a re-ground is proof about the commitment rather
#: than about the tick, which is the same discipline ``UNROUTABLE_GOAL_STEPS``
#: applies to a transient blockage.
HELD_RELEASE_AFTER: Final = 2

#: The body did not travel while the planner still had a route to execute —
#: NAV-CORE's stall class, and the 26/26 shape measured by NAV-GEN-1.
HELD_WITH_ROUTE: Final = "held_with_route_planned"
#: The planner has no route (``goal_blocked`` / ``no_path`` / nothing planned
#: yet). Not this module's business: ``_unroutable_goal_recovery`` owns it.
NO_ROUTE: Final = "no_route"
#: The body IS travelling and the range to the goal still is not falling — a
#: genuine "I am moving and not converging" stall (orbiting, a detour longer
#: than the watchdog window). Kept on the pre-C3 path deliberately.
DRIFTING: Final = "moving_without_converging"

#: Command note the held-stall release travels under. A distinct spelling from
#: ``semantic_replan_after_no_progress`` so the two paths are separable in any
#: trace, and from ``semantic_replan_after_blocked_route`` so card A2's own
#: witness keeps its meaning.
HELD_RELEASE_NOTE: Final = "semantic_replan_after_held_route"


def goal_progress_made(best_distance_m: float | None, distance_m: float) -> bool:
    """Did this tick beat the mission's best range to the goal?

    ``None`` (no reading yet) counts as progress so the first tick seeds the
    baseline rather than starting the stall count at 1.
    """

    return best_distance_m is None or distance_m < best_distance_m - PROGRESS_HYSTERESIS_M


def person_yield_holds(nearest_person_m: float | None, person_stop_m: float) -> bool:
    """Is this tick a person-yield rather than a stall?

    Yielding to a person is not a navigation stall — person-stop is the correct
    gate, and counting those ticks as "no progress" false-fails the N11
    pedestrian case before yield-advance can use its clear windows.

    Known gap, measured and NOT closed here (4/26 of the C3 stall class): the
    owner reaches ``apply_reactive_safety`` through ``observation.owner``, not
    through ``nearest_person_m``, so an owner standing in the corridor is not
    exempted by this clause. Widening it needs the hard tick cap and terminal
    reason that amendment A1 requires of any watchdog exemption, which is a
    bigger change than this card's dominant class; those episodes are instead
    classified :data:`HELD_WITH_ROUTE` below and take the bounded release door.
    """

    return nearest_person_m is not None and nearest_person_m < person_stop_m


def classify_stall(route_status: str | None, *, body_is_still: bool) -> str:
    """Name the stall the watchdog just fired on. One of the three constants.

    Read only two facts, both of which the navigator already maintains and
    neither of which is a gate verdict:

    * ``route_status`` — ``GridNavigator.last_route_status``, this tick's plan;
    * ``body_is_still`` — ``_update_body_stillness``, "the body has not
      travelled ``GATE_HOLD_DISPLACEMENT_M`` over this stretch of ticks", the
      witness card A2 chose precisely because goal jitter cannot reset it.

    That is the whole test. A gate that refuses a command it never told the
    navigator about (the runtime's final brake, 5+4 of the 26) is invisible to
    any brake-note witness but cannot hide from the odometer.
    """

    if route_status not in ROUTED_STATUSES:
        return NO_ROUTE
    return HELD_WITH_ROUTE if body_is_still else DRIFTING


def record_stall(metadata: dict, route_status: str | None, body_is_still: bool) -> int:
    """Write this stall's class into the mission record; return the held count.

    The mission record is the only state this card adds, and it is *data*:
    ``stall_class`` names what the watchdog just fired on, ``held_stalls``
    counts how many times this mission has been held with a route it never
    executed. Both travel with the mission for telemetry and for the verifier,
    and neither is read by any safety path.

    Returns 0 for any stall that is not :data:`HELD_WITH_ROUTE`, so the caller's
    release door is unreachable on every other class — the pre-C3 replan path
    stays byte-identical for them.
    """

    stall_class = classify_stall(route_status, body_is_still=body_is_still)
    metadata[STALL_CLASS_KEY] = stall_class
    if stall_class != HELD_WITH_ROUTE:
        return 0
    held = int(metadata.get(HELD_STALLS_KEY, 0)) + 1
    metadata[HELD_STALLS_KEY] = held
    return held


def held_release_due(
    metadata: dict,
    route_status: str | None,
    body_is_still: bool,
    *,
    enabled: bool,
) -> bool:
    """Is this stall a repeated held stall on an ARMED navigator?

    The flag gate is FIRST and it short-circuits, which is the whole contract
    card F1 requires: with :data:`HELD_RELEASE_FLAG` off this function reads
    nothing, writes nothing into ``metadata``, and returns ``False`` before any
    classification happens, so ``_progress_watchdog`` is byte-identical to the
    pre-C3 method. Off-path inertness is a property of this line, not of a
    convention — ``tests/test_stall_attribution.py`` asserts the untouched
    mapping.
    """

    if not enabled:
        return False
    return record_stall(metadata, route_status, body_is_still) >= HELD_RELEASE_AFTER
