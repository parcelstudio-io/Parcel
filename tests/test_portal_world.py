"""Card R14: the pins R10 wrote against an imagined door, run against a real one.

R10 shipped the arrival table's portal row and a planner guard for it, and
``tests/test_arrival_etiquette_pipeline.py`` proved both — against a
``DOOR_POLYGON`` literal invented in that test file, because no shipped scene
contained a door. E1's ``door-etiquette`` scenario then failed
``semantic_target_not_found`` for exactly that reason: "there is no scene in the
repo that contains the class the claim is about."

There is now. ``city_block.xml`` carries one ``door_1`` leaf and the sidecar
declares the class, so every geometric fact below is read out of the REAL scene
at test time rather than typed into this file. That is the whole point: a pin
whose geometry is hand-written cannot notice the scene moving underneath it,
which is the golden-file defect Wave 0 named.

Two kinds of test live here and they are labelled, because mixing them would be
dishonest:

* **CONTRACT** — what the product must do. A failure is a regression.
* **WITNESS** — what the product measurably does TODAY at a seam R14 found
  broken, pinned so the defect cannot be fixed, or worsened, without this file
  going red and forcing ``R14_STATUS.md`` and the E1 addendum to be revisited.
  Every witness names its defect id and says what it must become when fixed.
  A witness is not an endorsement.
"""

from __future__ import annotations

import math
from pathlib import Path

import mujoco
import pytest

from parcel_robot.city_semantics import extract_city_semantics
from parcel_robot.navigation.arrival_semantics import (
    CLASS_OBJECT,
    CLASS_PORTAL,
    FACE_OWNER,
    PORTAL_WORDS,
    arrival_fact,
    arrival_policy,
    classify_place,
)
from parcel_robot.navigation.base import GoalPose, NavObservation
from parcel_robot.navigation.goals import semantic_goal_from_directive
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.navigation.semantic_map import (
    SemanticCandidate,
    semantic_candidates_from_observation,
)
from parcel_robot.scene_semantics import DEFAULT_SIDECAR, load_scene_semantics

REPO = Path(__file__).resolve().parents[1]
SCENE = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
SIDECAR = REPO / DEFAULT_SIDECAR
MODELS = REPO / "configs" / "navigation" / "models"

#: The robot's footprint radius, as the arrival verifier reads it.
FOOTPRINT_M = 0.32

#: The owner, standing out on the road south of the entry wall.
OWNER_XY = (-5.4, 1.0)


# --------------------------------------------------------------- scene facts
@pytest.fixture(scope="module")
def scene():
    return mujoco.MjModel.from_xml_path(str(SCENE))


@pytest.fixture(scope="module")
def extraction(scene):
    return extract_city_semantics(scene)


@pytest.fixture(scope="module")
def portal(extraction):
    _, objects = extraction
    found = [item for item in objects if item["label"] == "door"]
    assert len(found) == 1, f"expected exactly one portal instance, got {found}"
    return found[0]


def _geom_half_extents(model: mujoco.MjModel, name: str) -> tuple[float, float]:
    """A geom's true PLANAR half-extents, read from the MJCF. Never typed.

    Type-aware on purpose: MuJoCo's ``geom_size`` means different things per
    type, and reading ``size[1]`` off a cylinder would hand back its half
    HEIGHT — which is how a round planter would look anisotropic and quietly
    invert the finding below.
    """

    geom_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
    assert geom_id >= 0, f"scene has no geom named {name!r}"
    geom_type = int(model.geom_type[geom_id])
    size = model.geom_size[geom_id]
    if geom_type in {
        int(mujoco.mjtGeom.mjGEOM_SPHERE),
        int(mujoco.mjtGeom.mjGEOM_CYLINDER),
    }:
        return float(size[0]), float(size[0])
    assert geom_type == int(mujoco.mjtGeom.mjGEOM_BOX), (
        f"{name!r} is geom type {geom_type}; this helper covers box/cylinder/sphere"
    )
    return float(size[0]), float(size[1])


def _portal_footprint(model: mujoco.MjModel, portal) -> tuple[tuple[float, float], ...]:
    """The door's own footprint polygon, derived from the scene.

    This is the polygon R10's pipeline test had to invent. It is the thing
    ``do_not_cross`` is *about*: the rectangle of ground the robot must not
    park its centre on.
    """

    hx, hy = _geom_half_extents(model, "door_1")
    cx, cy = float(portal["position"][0]), float(portal["position"][1])
    return (
        (cx - hx, cy - hy),
        (cx + hx, cy - hy),
        (cx + hx, cy + hy),
        (cx - hx, cy + hy),
    )


# ============================================================ CONTRACT: world
def test_the_shipped_city_contains_exactly_one_portal_instance(portal) -> None:
    """SEED S1 lands here: remove the class or the prefix and this goes red.

    E1's defect note in one assertion — "no shipped scene contains a portal".
    """

    assert portal["id"] == "door_1"
    semantics = load_scene_semantics(SIDECAR)
    assert semantics.has("door")
    assert ("door_", "door") in semantics.object_prefix_table()
    assert semantics.get("door").kind == "object"


def test_the_portals_class_word_is_one_the_arrival_table_calls_a_portal(portal) -> None:
    """The scene's class name and the arrival table's word list must agree.

    A scene may name its classes anything; the arrival table classifies by
    WORD. If the two ever diverge the scene would contain a doorway that the
    policy layer files as furniture, which is the failure mode R14 found in a
    different form (see the hosted-lane witness below).
    """

    assert portal["label"] in PORTAL_WORDS


def test_the_entry_wall_stubs_are_not_rival_door_candidates(extraction) -> None:
    """One doorway, one instance.

    ``city_semantics._instance_id`` files every geom of an unlisted class under
    its own name, so had the wall stubs carried the ``door_`` prefix the scene
    would ground three rival doors and every mission would be AMBIGUOUS. The
    stubs are deliberately unclassified; this is that decision, enforced.
    """

    _, objects = extraction
    assert [item["id"] for item in objects if item["label"] == "door"] == ["door_1"]


def test_the_portal_stands_on_a_supported_traversable_surface(portal) -> None:
    """"Reachably positioned" is a measurement, not an adjective.

    The leaf's own metadata must name the sidewalk as its support, because the
    ``near`` verifier refuses a terminal that is not on the target's support
    polygon (``_on_support_surface``). A door floating off the walkable set
    could never be arrived at by anything.
    """

    assert portal["metadata"]["support_label"] == "sidewalk"
    assert portal["metadata"]["support_polygon"]


def test_the_portals_approach_band_is_clear_of_the_pedestrian_routes(portal) -> None:
    """The card's "not inside pedestrian keepout churn", enforced.

    Every default city route is polled for its closest approach to the door's
    K0 near band. The band has to survive the crowd or the etiquette proof
    would be measuring yield policy instead.
    """

    from parcel_robot.dynamic_city import default_dynamic_agent_specs

    cx, cy = float(portal["position"][0]), float(portal["position"][1])
    outer = float(portal["metadata"]["vicinity_radius_m"])
    worst = min(
        math.hypot(point.x - cx, point.y - cy)
        for spec in default_dynamic_agent_specs()
        for point in spec.route
    )
    assert worst > outer, (
        f"a scripted city actor routes within {worst:.2f} m of the door centre, "
        f"inside its {outer:.2f} m approach band"
    )


# ======================================================= CONTRACT: the policy
def test_the_local_lane_reads_the_portal_row_for_the_scenes_own_door(portal) -> None:
    """SEEDS S3 and S4 land here: flip ``face`` or drop ``ask_hint`` -> red.

    The typed-panel lane (``agent.py``) and the brain router compile a
    directive with no scene vocabulary, so this is the arrival table answering
    on its own — which is what R10 designed it to do.
    """

    goal = semantic_goal_from_directive("go to the door")
    assert goal.place_class == CLASS_PORTAL
    assert goal.terminal_relation == "near"
    assert goal.face == FACE_OWNER
    assert goal.do_not_cross is True
    assert goal.ask_hint == "ask the owner what they would like to do next"

    fact = arrival_fact(
        place="the door", policy=arrival_policy(CLASS_PORTAL), owner_name="Jae"
    )
    assert "without going through it" in fact
    assert "turned back to face Jae" in fact
    assert fact.rstrip().endswith("ask the owner what they would like to do next.")


def test_a_terminal_inside_the_real_doorway_is_refused(scene, portal) -> None:
    """SEED S2 lands here. R10's guard, driven by the REAL leaf footprint.

    R10 could only test this against a polygon invented in the test file. The
    rectangle below is the one the scene actually contains, so a scene edit
    that moved or resized the leaf would move this test with it.
    """

    footprint = _portal_footprint(scene, portal)
    centre = (float(portal["position"][0]), float(portal["position"][1]))

    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS), grounder=PlaceGrounder([])
    )
    navigator.start("go to the door")
    goal = semantic_goal_from_directive("go to the door")
    candidate = SemanticCandidate(
        candidate_id=portal["id"],
        label=portal["label"],
        x=centre[0],
        y=centre[1],
        confidence=0.9,
        kind="object",
        polygon=footprint,
    )
    observation = NavObservation(
        position=(centre[0], centre[1] - 2.0, 0.0),
        heading_deg=90.0,
        extras={
            "lidar_obstacles": [],
            "owner_track": (
                {"x": OWNER_XY[0], "y": OWNER_XY[1], "vx": 0.0, "vy": 0.0, "radius_m": 0.35},
            ),
        },
    )

    in_the_threshold = GoalPose(x=centre[0], y=centre[1], heading_deg=0.0)
    assert (
        navigator._apply_arrival_etiquette(goal, candidate, observation, in_the_threshold)
        is None
    ), "the robot must stop AT the real door, never in it"
    assert navigator.mission is not None
    assert (
        navigator.mission.metadata["arrival_refused_reason"]
        == "portal_terminal_inside_threshold"
    )


def test_a_terminal_in_the_real_bands_south_arc_is_kept_and_faces_the_owner(
    scene, portal
) -> None:
    """SEED S3's other half: the kept pose turns back to the owner.

    The pose used here is inside the door's own K0 near band, read from the
    scene's metadata, so this is a pose the planner could really commit.
    """

    footprint = _portal_footprint(scene, portal)
    cx, cy = float(portal["position"][0]), float(portal["position"][1])
    band_lo = float(portal["metadata"]["minimum_vicinity_radius_m"])
    band_hi = float(portal["metadata"]["vicinity_radius_m"])
    stand = (cx, cy - (band_lo + band_hi) / 2.0)
    assert band_lo <= math.hypot(stand[0] - cx, stand[1] - cy) <= band_hi

    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS), grounder=PlaceGrounder([])
    )
    navigator.start("go to the door")
    goal = semantic_goal_from_directive("go to the door")
    candidate = SemanticCandidate(
        candidate_id=portal["id"],
        label=portal["label"],
        x=cx,
        y=cy,
        confidence=0.9,
        kind="object",
        polygon=footprint,
    )
    observation = NavObservation(
        position=(stand[0], stand[1] - 1.0, 0.0),
        heading_deg=90.0,
        extras={
            "lidar_obstacles": [],
            "owner_track": (
                {"x": OWNER_XY[0], "y": OWNER_XY[1], "vx": 0.0, "vy": 0.0, "radius_m": 0.35},
            ),
        },
    )

    kept = navigator._apply_arrival_etiquette(
        goal, candidate, observation, GoalPose(x=stand[0], y=stand[1], heading_deg=0.0)
    )
    assert kept is not None, "the guard refuses the threshold, not the errand"
    assert (kept.x, kept.y) == stand
    assert kept.heading_deg == math.degrees(
        math.atan2(OWNER_XY[1] - stand[1], OWNER_XY[0] - stand[0])
    )
    assert navigator.mission is not None
    assert navigator.mission.metadata["arrival_face_applied"] == FACE_OWNER


# ================================================================= WITNESSES
def test_witness_R14_D1_the_hosted_lane_files_the_door_as_furniture(portal) -> None:
    """**WITNESS — defect R14-D1. Not a contract. Do not read as intended.**

    ``classify_place`` checks the caller-supplied scene vocabulary as a WHOLE
    PHRASE before it checks its own portal word list against the head noun.
    ``semantic_goal_from_directive`` strips the leading article, so the owner's
    "go to the door" arrives as the bare token ``door`` — and the moment the
    sidecar declares a class of that name, the bare token matches the scene
    vocabulary and the place is classified ``object``.

    The consequence is a split brain that only R14's world could expose:

    * the typed panel and the brain router pass NO vocabulary, so they get
      ``portal`` — do-not-cross on, ask-hint on (the contract test above);
    * ``runtime._realtime_navigate`` folds ``_realtime_scene_vocabulary()`` in,
      so the HOSTED lane — the one E1 actually drove — gets ``object``, with
      ``do_not_cross`` False and no ask-hint.

    The extension mechanism is implemented as an override. Adding the door to
    the sidecar is what flips the hosted lane, so this defect was created by
    giving the scene the thing it was missing.

    **When R14-D1 is fixed**, both lanes answer ``portal`` and this test must be
    DELETED, not adjusted — and the E1 door-etiquette addendum re-run.
    """

    semantics = load_scene_semantics(SIDECAR)
    scene_objects = tuple(
        word
        for item in semantics.classes
        if item.kind != "region"
        for word in (item.name, *item.aliases)
    )
    scene_regions = tuple(
        word
        for item in semantics.classes
        if item.kind == "region"
        for word in (item.name, *item.aliases)
    )

    assert portal["label"] in scene_objects, "precondition: the scene supplies the word"

    hosted = semantic_goal_from_directive(
        "go to the door", region_labels=scene_regions, object_labels=scene_objects
    )
    local = semantic_goal_from_directive("go to the door")

    assert local.place_class == CLASS_PORTAL
    assert hosted.place_class == CLASS_OBJECT, (
        "R14-D1 appears to be FIXED: the hosted lane now classifies the door as "
        "a portal. Delete this witness and re-run the E1 door-etiquette addendum."
    )
    assert hosted.do_not_cross is False
    assert hosted.ask_hint == ""
    # The narration channel disagrees with the planner in the same breath: the
    # runtime hands `_arrival_fact_for` the mission's semantic_query, which is
    # the same stripped token, so the owner is told the object sentence.
    assert "without going through it" not in arrival_fact(
        place="the door", policy=arrival_policy(hosted.place_class), owner_name="Jae"
    )
    # ...while an UNSTRIPPED phrase escapes the whole-phrase match and gets the
    # portal sentence. Same door, same run, two answers.
    assert classify_place("the door", object_labels=scene_objects) == CLASS_PORTAL


def test_witness_R14_D2_the_do_not_cross_guard_has_no_polygon_to_test(portal) -> None:
    """**WITNESS — defect R14-D2. Not a contract.**

    ``_apply_arrival_etiquette`` refuses a threshold pose only when
    ``result.polygon`` is non-empty. The shipping perception seam
    (``semantic_candidates_from_observation``) emits ``polygon`` for REGION
    tracks only; object tracks carry ``position`` and ``metadata`` and nothing
    else. A portal is necessarily object-kind, because ``ObservationSemanticMap``
    filters on ``candidate.kind == goal.kind`` and the portal row's goal kind is
    ``object``.

    So on the product path the guard's precondition is never met, and the pin
    two tests above passes only because it hands the guard a polygon the
    runtime would never give it. The etiquette holds today by the ``near``
    band's own arithmetic — a band pose is outside the leaf by construction —
    and not by the guard that was written to enforce it.

    **When R14-D2 is fixed** (an object track carrying its footprint, most
    likely), this test must be DELETED and the do-not-cross claim re-measured
    end to end.
    """

    from parcel_robot.headless_city import HeadlessCityWorld

    world = HeadlessCityWorld(SCENE)
    doors: list[dict] = []
    objects: list[dict] = []
    regions: list[dict] = []
    # Two poses, because one frustum rarely holds both the leaf and a region
    # centroid: the asymmetry is a property of the SEAM, not of one viewpoint.
    for pose in (
        (float(portal["position"][0]), 1.2, math.pi / 2.0),
        (float(portal["position"][0]) + 1.0, 2.6, 0.0),
    ):
        observation = world.reset(robot=pose, owner=OWNER_XY)
        for item in semantic_candidates_from_observation(observation):
            if item.get("kind") == "region":
                regions.append(item)
            else:
                objects.append(item)
                if item.get("label") == "door":
                    doors.append(item)

    assert doors, "precondition: the robot can see the door from the road"
    assert regions, "precondition: the robot can see a region from the sidewalk"
    assert all(not item.get("polygon") for item in objects), (
        "R14-D2 appears to be FIXED at the perception seam: object tracks now "
        "carry a polygon. Delete this witness and re-measure do-not-cross end "
        "to end."
    )
    assert all(item.get("polygon") for item in regions), (
        "regions still carry polygons, so the asymmetry is the finding"
    )

    # The CONSEQUENCE, not just the precondition. Pinning only the seam let an
    # inverse seed repair the guard while this test stayed green (R14 seed S10,
    # recorded GREEN and then strengthened rather than deleted). Feed the guard
    # the candidate the runtime would REALLY build — a door track with no
    # polygon — with a pose squarely inside the leaf's own footprint, and watch
    # it wave the pose through.
    door_track = doors[0]
    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS), grounder=PlaceGrounder([])
    )
    navigator.start("go to the door")
    goal = semantic_goal_from_directive("go to the door")
    assert goal.do_not_cross is True, "precondition: the local lane wants the guard"
    runtime_shaped = SemanticCandidate(
        candidate_id=str(door_track["id"]),
        label=str(door_track["label"]),
        x=float(door_track["position"][0]),
        y=float(door_track["position"][1]),
        confidence=float(door_track.get("confidence", 0.9)),
        kind="object",
        polygon=(),  # exactly what the seam emits
    )
    in_the_threshold = GoalPose(
        x=float(portal["position"][0]), y=float(portal["position"][1]), heading_deg=0.0
    )
    observation = NavObservation(
        position=(float(portal["position"][0]), float(portal["position"][1]) - 2.0, 0.0),
        heading_deg=90.0,
        extras={
            "lidar_obstacles": [],
            "owner_track": (
                {"x": OWNER_XY[0], "y": OWNER_XY[1], "vx": 0.0, "vy": 0.0, "radius_m": 0.35},
            ),
        },
    )
    waved_through = navigator._apply_arrival_etiquette(
        goal, runtime_shaped, observation, in_the_threshold
    )
    assert waved_through is not None, (
        "R14-D2 appears to be FIXED at the guard: a threshold pose is now "
        "refused even when the candidate carries no polygon. Delete this "
        "witness and re-measure do-not-cross end to end."
    )
    assert navigator.mission is not None
    assert "arrival_refused_reason" not in navigator.mission.metadata


def test_witness_R14_D3_the_near_verifier_only_agrees_with_round_anchors(
    scene, extraction
) -> None:
    """**WITNESS — defect R14-D3. PRE-EXISTING; the door only makes it vivid.**

    The ``near`` arrival authority is two different geometries wearing one name.

    * The planner's goal region (``object_near_goal_region``) is a band on the
      distance to the anchor POINT, sized with the anchor's CIRCUMSCRIBED
      radius: ``[r + 1.12, r + 1.32]``.
    * The verifier (``pipeline._semantic_arrival_verified``, relation ``near``)
      re-expresses that band as a LiDAR surface band by subtracting the same
      circumscribed radius and the footprint: ``[0.80, 1.00]``, a constant.

    The subtraction is exact only if the anchor is a disc. For any anisotropic
    anchor the two predicates disagree by ``r - short_half_extent``, and the
    planner can commit — inside its own band, with full confidence — a pose the
    verifier is guaranteed to reject.

    This is NOT new with R14: ``bench_1`` (aspect 3.18) and ``bldg_1`` already
    fail the same arithmetic, and a live "go to the bench" in the headless rig
    ends ``semantic_target_unreachable`` today. The door leaf (aspect 6.67) is
    simply the sharpest case, and it is the one that matters because the portal
    row's terminal relation IS ``near``.

    **When R14-D3 is fixed**, the head-on-satisfiable column below goes true for
    the anisotropic anchors and this test must be DELETED.
    """

    _, objects = extraction
    by_id = {item["id"]: item for item in objects}

    def head_on_satisfiable(instance_id: str, geom_name: str) -> bool:
        item = by_id[instance_id]
        _, short = _geom_half_extents(scene, geom_name)
        radius = float(item["metadata"]["radius_m"])
        band = item["metadata"]["goal_region"]["band_m"]
        return (radius - short) <= (float(band[1]) - float(band[0])) + 1e-9

    # Round anchors: the two predicates are the same predicate.
    assert head_on_satisfiable("lamp_post_1", "lamp_post_1")
    assert head_on_satisfiable("planter_1", "planter_1")
    assert head_on_satisfiable("tree_1", "tree_top_1")
    # Anisotropic anchors: they are not. The bench pre-dates R14 by a fortnight.
    assert not head_on_satisfiable("bench_1", "bench_seat"), (
        "R14-D3 appears to be FIXED for the bench — delete this witness"
    )
    assert not head_on_satisfiable("door_1", "door_1"), (
        "R14-D3 appears to be FIXED for the door. Delete this witness and "
        "re-run the E1 door-etiquette addendum: the geometry half of the claim "
        "may now be provable end to end."
    )


def test_witness_R14_D4_the_portal_is_not_in_the_headless_obstacle_set() -> None:
    """**WITNESS — defect R14-D4. Not a contract.**

    ``headless_city._STATIC_OBSTACLE_PREFIXES`` is a hand-maintained tuple of
    geom-name prefixes, entirely separate from the sidecar's prefix tables. The
    door and its entry wall are absent from it, so in the quality rig the block's
    only portal casts no LiDAR return and takes part in no collision count — a
    second scene vocabulary that nothing keeps in step with the first.

    Measured, not inferred: splicing ``door_`` into that tuple at runtime does
    not change the mission's outcome (both end
    ``semantic_arrival_verification_failed`` at the same pose), because R14-D3
    rejects the terminal either way. That is why this is filed as its own defect
    rather than as the cause of anything.

    **When R14-D4 is fixed**, delete this witness.
    """

    from parcel_robot import headless_city
    from parcel_robot.scene_semantics import scene_semantics

    prefixes = headless_city._STATIC_OBSTACLE_PREFIXES
    assert "door_" not in prefixes, (
        "R14-D4 appears to be FIXED — delete this witness and re-measure the rig"
    )
    declared = {prefix for prefix, _ in scene_semantics().object_prefix_table()}
    missing = sorted(
        prefix
        for prefix in declared
        if not any(prefix.startswith(known) for known in prefixes)
    )
    assert missing == ["door_"], (
        f"the sidecar and the rig's obstacle tuple disagree about {missing}; "
        "R14 found one such disagreement and this pins the count"
    )
