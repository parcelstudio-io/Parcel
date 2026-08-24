"""NAV-CORE's capability probe: is the room a fair room, and is the alias real?

Thin by design (the DESIGN says so).  It pins the two premises the study's
numbers rest on, both of which are properties of the harness rather than of the
product, and both of which would silently invalidate the rows if they drifted:

1. **The arrival bar is reachable.**  Every stored place and every start pose
   keeps at least ``MIN_PLACE_CLEARANCE_M`` of room in every layout, so a
   missed arrival is the navigator's result and not the furniture's.
2. **The aliased world is actually aliased.**  A pose and its 180 degree image
   produce scans that agree to float noise, and the whole-map matcher's
   second-best margin collapses there while staying wide in a normal layout —
   which is what makes refuter 4b a false-healthy test rather than a large
   displacement the matcher happens to miss.

It also pinned the one product behaviour the study depends on being able to
observe: the learned-map ingress emits ``kind="object"`` rows only, while the
goal grammar classes "bed" as a REGION goal, so that goal could never resolve
under the ``learned_map`` source.

**PORTED 2026-08-24 by card A2 (NAV-GLUE).** That defect is fixed —
``ObservationSemanticMap.query`` is strict-first, tolerant-only-when-strict-
finds-nothing — so the case below no longer asserts the disagreement stands.
It keeps the two halves the STUDY depends on (the grammar's classes and the
room's labels) and hands the fix's own pin to
``tests/test_a2_navglue.py::test_a_region_goal_now_resolves_against_the_learned_maps_object_rows``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "research" / "20260824" / "nav-core"
pytest.importorskip("mujoco")
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def test_every_place_and_start_has_room_to_stand_in_every_layout() -> None:
    from room import MIN_PLACE_CLEARANCE_M, audit_clearances

    worst = audit_clearances()
    offenders = {
        name: round(value, 3)
        for name, value in worst.items()
        if value < MIN_PLACE_CLEARANCE_M
    }
    assert not offenders, (
        "the NAV-CORE room would be measuring its own furniture: "
        f"{offenders} fall below {MIN_PLACE_CLEARANCE_M} m of clearance"
    )


def test_the_aliased_world_is_aliased_to_float_noise() -> None:
    from room import alias_scan_agreement

    disagreement = alias_scan_agreement()
    assert disagreement < 1e-9, (
        "refuter 4b needs a kidnap the scan cannot see; the C2 image disagrees "
        f"by {disagreement} m, so the corridor is not aliased"
    )


def test_the_whole_map_margin_separates_a_normal_room_from_an_aliased_one() -> None:
    import numpy as np
    from relocalize import MARGIN_MIN, GlobalMatcher
    from room import ALIASED_START, RoomWorld

    normal = RoomWorld(3)
    truth = (-0.8, 1.2, 0.7)
    match = GlobalMatcher(normal).match(normal.scan(*truth, np.random.default_rng(5)))
    assert math.dist(match.pose[:2], truth[:2]) <= 0.15
    assert match.margin >= MARGIN_MIN

    aliased = RoomWorld("aliased")
    ambiguous = GlobalMatcher(aliased).match(
        aliased.scan(*ALIASED_START, np.random.default_rng(5))
    )
    assert ambiguous.margin < MARGIN_MIN, (
        "A4's re-arm path (a) must be unavailable in an aliased corridor; "
        f"the margin measured {ambiguous.margin}"
    )


def test_the_corpus_asks_both_kinds_of_goal_and_the_map_still_answers() -> None:
    """PORTED by card A2 — the premise, now that the defect behind it is fixed.

    The two facts the corpus rests on are unchanged and still checked here:
    ``goals.semantic_goal_from_directive('bed')`` is a REGION goal (R10's
    place-class table) while "kitchen counter" is an OBJECT goal, and the room
    labels both, so the corpus exercises both halves of the join.  What changed
    is the join: ``ObservationSemanticMap.query`` no longer requires the goal's
    kind and the map's kind to be the same word, so the twelve ``bed`` episodes
    that answered ``not_found`` now resolve.  The learned-map ingress still
    stamps ``kind='object'`` — that was never a measurement and A2 did not make
    it one.
    """

    from parcel_robot.navigation.base import NavObservation
    from parcel_robot.navigation.goals import semantic_goal_from_directive
    from parcel_robot.navigation.semantic_map import ObservationSemanticMap

    assert semantic_goal_from_directive("bed").kind == "region"
    assert semantic_goal_from_directive("kitchen counter").kind == "object"

    from room import PLACES

    assert {place.label for place in PLACES} >= {"bed", "kitchen counter"}

    observation = NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        extras={
            "perception_fresh": True,
            "semantic_candidates": [
                {
                    "id": "place-bed",
                    "label": "bed",
                    "kind": "object",  # what the learned-map ingress stamps
                    "position": [1.0, 0.0, 0.0],
                    "confidence": 0.9,
                    "source": "online_map",
                    "reachable": True,
                    "metadata": {"semantic_source": "learned_map"},
                }
            ],
        },
    )
    resolved = ObservationSemanticMap().query(
        semantic_goal_from_directive("bed"), observation
    )
    assert [item.candidate_id for item in resolved] == ["place-bed"]
