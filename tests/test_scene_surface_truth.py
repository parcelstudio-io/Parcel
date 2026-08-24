"""The answer key a sensor can actually measure (card PG-2).

WHAT IS PINNED HERE, AND WHY EACH THING IS PINNED
-------------------------------------------------
1. **The surface table is derived, never typed.** Same contract
   ``tests/test_nav_instruct_scene_truth.py`` already holds for ``derived``: the
   checked-in ``surfaces`` section must equal a fresh derivation from
   ``city_block.xml``, so a hand edit or a skipped regeneration is a red build.
2. **`inside`-class arrival is untouched.** Every region's ``interior_polygon``
   is byte-identical to that region's ``derived`` polygon and to the goal-region
   polygon ``city_semantics`` hands the navigator. R10's containment arrival is
   the same predicate over the same numbers it was before this card.
3. **`near`-class perception is graded to the surface.** A point on a building's
   visible facade scores centimetres; the geom centre scores 1.2–1.7 m and fails
   the budget. That inversion is the whole card: the 2026-08-21 mapping bench
   measured real fused entries landing on the facade 6/6 in its oracle arm, and
   the old key called every one of them a failure.
4. **A localization claim cannot exist without its null control.** The bench
   scored sidewalk and crosswalk at 0.00 m against a *random* map (p=1.00 and
   p=0.52). A statistic that passes but does not beat chance is
   ``uninformative`` — explicitly not a pass — and ``verdict`` is a property no
   caller can overwrite.
5. **Large regions get a metric a random map cannot pass.** Bare containment is
   kept as the arrival predicate and is *not sufficient*: the answering entry's
   own evidence must also be majority-inside, and the null must agree.

None of these tests read anything outside the repo. The bench's own artifacts
live in a scratch directory that will not survive; the facts they established
are re-derived here from ``city_block.xml`` so they stay checkable forever.
"""

from __future__ import annotations

import json

import pytest

from evals.nav_instruct.scene_truth import (
    ARTIFACT_VERSION,
    SCENE_PATH,
    SURFACE_CONVENTION_VERSION,
    SurfaceDerivationError,
    build_artifact,
    derive_scene_surfaces,
    derive_scene_truth,
    load_artifact,
    surface_table,
)
from evals.nav_instruct.surface_scoring import (
    DIRECTION_LOWER_IS_BETTER,
    MIN_NULL_DRAWS,
    NULL_ALPHA,
    REGION_EVIDENCE_MAJORITY,
    SURFACE_BUDGET_M,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_UNINFORMATIVE,
    LocalizationClaim,
    MappedArea,
    NullControl,
    SurfaceScoringError,
    evidence_inside_fraction,
    interior_contains,
    score_inside_class,
    score_localization,
    score_near_class,
    surface_error_m,
    visible_facade,
)
from parcel_robot.instructnav.scoring import object_near_goal_region
from parcel_robot.navigation.arrival_semantics import (
    ARRIVAL_TABLE,
    CLASS_OBJECT,
    CLASS_PORTAL,
    CLASS_REGION,
    LOCALIZATION_INTERIOR,
    LOCALIZATION_SURFACE,
    LOCALIZATION_TARGETS,
    PLACE_CLASSES,
    RELATION_INSIDE,
    arrival_policy,
    classify_place,
    localization_target,
    planner_relation,
)
from parcel_robot.perception.city_semantics import extract_city_semantics
from parcel_robot.perception.scene_semantics import scene_semantics

#: The six buildings, their geom centre and half-extent, read straight off
#: ``city_block.xml``. Kept here as the INDEPENDENT half of the proof: the
#: derivation is checked against numbers a reader can find in the scene file by
#: eye, not against its own output.
BUILDING_GEOMS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "bldg_1": ((-4.5, 5.5), (1.8, 1.5)),
    "bldg_2": ((-1.0, 5.8), (1.4, 1.2)),
    "bldg_3": ((2.2, 5.6), (1.5, 1.4)),
    "bldg_4": ((5.5, 5.4), (1.6, 1.5)),
    "bldg_5": ((-5.5, -4.5), (1.7, 1.4)),
    "bldg_6": ((5.0, -5.0), (1.8, 1.6)),
}


@pytest.fixture(scope="module")
def artifact() -> dict:
    return load_artifact()


@pytest.fixture(scope="module")
def surfaces() -> dict:
    return surface_table()


@pytest.fixture(scope="module")
def derived() -> dict:
    return load_artifact()["derived"]


@pytest.fixture(scope="module")
def scene_vocabulary() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Region / object words, exactly as ``runtime._realtime_scene_vocabulary``
    builds them from the sidecar: class names plus aliases."""

    regions: list[str] = []
    objects: list[str] = []
    for scene_class in scene_semantics().classes:
        bucket = regions if scene_class.kind == "region" else objects
        bucket.append(scene_class.name)
        bucket.extend(scene_class.aliases)
    return tuple(regions), tuple(objects)


def _visible_face_y(centre: tuple[float, float], half: tuple[float, float]) -> float:
    """The face of a north/south building that looks at the street (y=0)."""

    return centre[1] - half[1] if centre[1] > 0 else centre[1] + half[1]


# ==================================================== 1. the table is derived


def test_the_checked_in_surfaces_equal_a_fresh_derivation(surfaces: dict) -> None:
    """A hand edit of the artifact, or a scene edit that skipped regeneration."""

    assert surfaces == derive_scene_surfaces(), (
        "scene_truth.json's surfaces section is stale or hand-edited. "
        "Regenerate with:\n"
        "  .parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate"
    )


def test_the_whole_artifact_still_equals_a_fresh_build(artifact: dict) -> None:
    """The v1 contract, re-asserted now that the artifact carries more."""

    assert artifact == build_artifact()


def test_every_derived_entity_has_a_measurable_surface(
    surfaces: dict, derived: dict
) -> None:
    """No entity may be present in the answer key with no sensor-measurable target.

    A missing surface reads to a scorer as "this place cannot be measured", and
    the fallback anybody would reach for is the centre — the exact defect this
    card closed.
    """

    assert set(surfaces) == set(derived)


def test_the_artifact_is_versioned_and_self_describing(artifact: dict) -> None:
    assert artifact["artifact_version"] == ARTIFACT_VERSION >= 2
    convention = artifact["surface_convention"]
    assert convention["version"] == SURFACE_CONVENTION_VERSION
    # The rules travel WITH the answer key, so a reader months from now does not
    # have to find the scoring module before they can read a number.
    assert set(convention["measures"]) == set(LOCALIZATION_TARGETS)
    assert convention["null_control"]["required"] is True
    assert convention["null_control"]["min_draws"] == MIN_NULL_DRAWS
    assert convention["null_control"]["alpha"] == NULL_ALPHA
    assert set(convention["null_control"]["verdicts"]) == {
        VERDICT_PASS,
        VERDICT_FAIL,
        VERDICT_UNINFORMATIVE,
    }


def test_a_v1_artifact_is_refused_rather_than_read_as_empty(tmp_path) -> None:
    """An empty surface table and a missing one look identical to a scorer."""

    stale = json.loads(json.dumps(load_artifact()))
    stale["artifact_version"] = 1
    stale.pop("surfaces")
    path = tmp_path / "scene_truth.json"
    path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(KeyError, match="predates the surface convention"):
        surface_table(path)


def test_every_object_part_names_a_real_geom_of_that_instance(
    surfaces: dict,
) -> None:
    """The nearest-surface set is the instance's own geoms, in extraction order."""

    import mujoco

    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    _regions, objects = extract_city_semantics(model)
    by_id = {str(item["id"]): item for item in objects}
    for entity_id, record in surfaces.items():
        if record["kind"] != "object":
            continue
        expected = list(by_id[entity_id]["metadata"]["associated_lidar_ids"])
        assert [part["geom"] for part in record["parts"]] == expected, entity_id
        assert record["parts"], entity_id


def test_a_rotated_box_is_refused_rather_than_flattened(tmp_path) -> None:
    """A rotated box's footprint is NOT the axis-aligned rectangle we emit."""

    scene = tmp_path / "rotated.xml"
    scene.write_text(
        """<mujoco>
  <worldbody>
    <geom name="sidewalk" type="box" pos="0 3.2 0.06" size="8 1.0 0.06"/>
    <geom name="bldg_1" type="box" pos="-4.5 5.5 2.0" size="1.8 1.5 2.0"
          euler="0 0 30"/>
  </worldbody>
</mujoco>
""",
        encoding="utf-8",
    )
    with pytest.raises(SurfaceDerivationError, match="rotated box"):
        derive_scene_surfaces(scene)


# ================================== 2. inside-class arrival is byte-unaffected


def test_every_region_interior_is_byte_identical_to_its_derived_polygon(
    surfaces: dict, derived: dict
) -> None:
    """THE `inside`-class guarantee. Same numbers, same predicate, same arrival."""

    regions = {k: v for k, v in surfaces.items() if v["kind"] == "region"}
    assert regions, "the scene must still contain regions"
    for entity_id, record in regions.items():
        assert record["interior_polygon"] == derived[entity_id]["polygon"], entity_id


def test_region_goal_regions_handed_to_the_navigator_are_the_same_polygon(
    surfaces: dict,
) -> None:
    """Not just equal to the answer key — equal to what the ROBOT is given."""

    import mujoco

    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    regions, _objects = extract_city_semantics(model)
    for region in regions:
        record = surfaces[str(region["id"])]
        goal_polygon = region["metadata"]["goal_region"]["polygon"]
        assert [[round(p[0], 6), round(p[1], 6)] for p in goal_polygon] == record[
            "interior_polygon"
        ], region["id"]


def test_inside_class_places_still_classify_and_terminate_inside(
    surfaces: dict, scene_vocabulary
) -> None:
    region_labels, object_labels = scene_vocabulary
    for entity_id, record in surfaces.items():
        if record["kind"] != "region":
            continue
        place_class = classify_place(
            record["label"], region_labels=region_labels, object_labels=object_labels
        )
        assert place_class == CLASS_REGION, entity_id
        assert arrival_policy(place_class).relation == RELATION_INSIDE
        assert planner_relation(RELATION_INSIDE) == RELATION_INSIDE
        assert record["measure"] == LOCALIZATION_INTERIOR


# ========================== 3. the arrival table is the authority on the measure


def test_every_measure_is_read_from_the_arrival_table(
    surfaces: dict, scene_vocabulary
) -> None:
    """The answer key holds no class -> metric map of its own."""

    region_labels, object_labels = scene_vocabulary
    for entity_id, record in surfaces.items():
        place_class = classify_place(
            record["label"], region_labels=region_labels, object_labels=object_labels
        )
        assert record["place_class"] == place_class, entity_id
        assert record["measure"] == localization_target(place_class), entity_id


def test_the_arrival_table_answers_the_measure_for_every_class() -> None:
    assert set(ARRIVAL_TABLE) == set(PLACE_CLASSES)
    for name, policy in ARRIVAL_TABLE.items():
        assert policy.localization_target in LOCALIZATION_TARGETS, name
    # The split that matters: exactly the containment class is measured inside.
    assert localization_target(CLASS_REGION) == LOCALIZATION_INTERIOR
    for name in PLACE_CLASSES:
        if name != CLASS_REGION:
            assert localization_target(name) == LOCALIZATION_SURFACE, name
    assert localization_target("a class nobody declared") == LOCALIZATION_SURFACE


def test_the_door_is_measured_to_its_surface_under_either_classification(
    surfaces: dict, scene_vocabulary
) -> None:
    """Immunity to the known R14-D1 classification defect.

    ``classify_place`` checks the caller-supplied scene vocabulary as a whole
    phrase before it checks ``PORTAL_WORDS`` against the head noun, so the bare
    token ``door`` classifies as ``object`` when the sidecar declares a class of
    that name and as ``portal`` when it does not. That is a live, already-
    reported defect (``scrum/20260820/task_3/R14_STATUS.md`` R14-D1) and this
    card does not touch it. What this test pins is that PG-2's answer key does
    not CARE which way it is eventually fixed: both rows are measured to the
    surface, so the door's grading target cannot move underneath us.
    """

    region_labels, object_labels = scene_vocabulary
    with_vocabulary = classify_place(
        "door", region_labels=region_labels, object_labels=object_labels
    )
    without_vocabulary = classify_place("door")
    assert with_vocabulary == CLASS_OBJECT
    assert without_vocabulary == CLASS_PORTAL
    assert localization_target(with_vocabulary) == LOCALIZATION_SURFACE
    assert localization_target(without_vocabulary) == LOCALIZATION_SURFACE
    assert surfaces["door_1"]["measure"] == LOCALIZATION_SURFACE


# ================================== 4. the re-grade: facade passes, centre fails


@pytest.mark.parametrize("entity_id", sorted(BUILDING_GEOMS))
def test_a_point_on_the_visible_facade_scores_centimetres(
    entity_id: str, surfaces: dict
) -> None:
    """What the bench's fused entries actually are: points on the front face."""

    centre, half = BUILDING_GEOMS[entity_id]
    facade_point = (centre[0], _visible_face_y(centre, half))
    error = surface_error_m(facade_point, surfaces[entity_id])
    assert error == pytest.approx(0.0, abs=1e-9)
    assert error <= SURFACE_BUDGET_M


@pytest.mark.parametrize("entity_id", sorted(BUILDING_GEOMS))
def test_the_geom_centre_fails_the_surface_budget_by_the_measured_margin(
    entity_id: str, surfaces: dict, derived: dict
) -> None:
    """The old convention's answer, re-measured. 1.2-1.7 m, 6/6 — the bench's
    number, re-derived from the scene rather than trusted."""

    centre, half = BUILDING_GEOMS[entity_id]
    assert derived[entity_id]["position"] == [centre[0], centre[1]]
    error = surface_error_m(centre, surfaces[entity_id])
    # The centre is exactly the smaller half-extent away from the nearest face.
    assert error == pytest.approx(min(half), abs=1e-9)
    assert 1.2 <= error <= 1.7, entity_id
    assert error > SURFACE_BUDGET_M, entity_id


def test_a_real_sensor_offset_from_the_facade_passes_where_the_centre_failed(
    surfaces: dict,
) -> None:
    """The inversion, on one worked example, in one assertion each way.

    ``bldg_1``: centre (-4.5, 5.5), visible face y=4.0. A fused entry 3 cm off
    the facade — the bench's own worst oracle-arm offset — is a PASS at the
    repo's 0.30 m budget and was a 1.5 m FAIL against the centre.
    """

    surface = surfaces["bldg_1"]
    sensed = (-4.5, 3.97)
    assert surface_error_m(sensed, surface) == pytest.approx(0.03, abs=1e-9)
    assert surface_error_m(sensed, surface) <= SURFACE_BUDGET_M
    centre_error = abs(3.97 - 5.5)
    assert centre_error == pytest.approx(1.53, abs=1e-9)
    assert centre_error > SURFACE_BUDGET_M


def test_surface_error_is_unsigned_so_a_point_inside_a_solid_is_wrong(
    surfaces: dict,
) -> None:
    """No depth ray produced a point in the middle of a building."""

    inside_the_block = (-4.5, 5.5)
    assert surface_error_m(inside_the_block, surfaces["bldg_1"]) > 0.0


def test_a_multi_part_object_measures_to_whichever_part_faces_the_robot(
    surfaces: dict,
) -> None:
    """The bench is four box geoms; a ray hits the one in front of it.

    ``bench_seat`` spans y 2.78..3.22, ``bench_back`` 3.13..3.23. A robot on the
    south side sees the seat's front face at y=2.78 and must score ~0 there,
    even though the instance's merged centre is at y=3.045.
    """

    surface = surfaces["bench_1"]
    assert len(surface["parts"]) == 4
    front_of_seat = (-2.5, 2.78)
    assert surface_error_m(front_of_seat, surface) == pytest.approx(0.0, abs=1e-9)
    merged_centre = (-2.5, 3.045)
    assert surface_error_m(merged_centre, surface) > 0.0


def test_a_cylinder_measures_to_its_shell_not_its_axis(surfaces: dict) -> None:
    """The lamppost: a 0.06 m pole the bench localized to 1-3 cm."""

    surface = surfaces["lamp_post_1"]
    assert surface["parts"][0]["shape"] == "circle"
    on_the_shell = (0.2 + 0.06, 3.15)
    assert surface_error_m(on_the_shell, surface) == pytest.approx(0.0, abs=1e-12)
    assert surface_error_m((0.2, 3.15), surface) == pytest.approx(0.06, abs=1e-12)


def test_a_region_record_cannot_be_scored_by_the_surface_rule(surfaces: dict) -> None:
    with pytest.raises(SurfaceScoringError, match="measured by 'interior'"):
        surface_error_m((0.0, 3.2), surfaces["sidewalk"])


def test_an_object_record_cannot_be_scored_by_the_containment_rule(
    surfaces: dict,
) -> None:
    with pytest.raises(SurfaceScoringError, match="measured by 'surface'"):
        interior_contains((-4.5, 4.0), surfaces["bldg_1"])


# ====================================== 5. the null control is not optional


def _null(observed: float = 0.01, at_least_as_good: int = 0) -> NullControl:
    return NullControl(
        statistic="surface_error_m",
        direction=DIRECTION_LOWER_IS_BETTER,
        observed=observed,
        draws=MIN_NULL_DRAWS,
        seed=1,
        at_least_as_good=at_least_as_good,
        null_median=1.0,
        null_tail=0.5,
        area=MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0)),
        population="map entries",
        population_size=36,
    )


def test_a_localization_claim_cannot_be_built_without_a_null_control() -> None:
    """The card's rule, enforced by the type rather than by remembering it."""

    with pytest.raises(TypeError):
        LocalizationClaim(  # type: ignore[call-arg]
            entity_id="bldg_1",
            label="building",
            place_class=CLASS_OBJECT,
            measure=LOCALIZATION_SURFACE,
            statistic="surface_error_m",
            value=0.01,
            threshold=SURFACE_BUDGET_M,
            raw_pass=True,
        )
    with pytest.raises(SurfaceScoringError, match="requires a NullControl"):
        LocalizationClaim(
            entity_id="bldg_1",
            label="building",
            place_class=CLASS_OBJECT,
            measure=LOCALIZATION_SURFACE,
            statistic="surface_error_m",
            value=0.01,
            threshold=SURFACE_BUDGET_M,
            raw_pass=True,
            null=None,  # type: ignore[arg-type]
        )


def test_a_null_control_below_the_draw_floor_is_refused() -> None:
    with pytest.raises(SurfaceScoringError, match="below the"):
        NullControl(
            statistic="surface_error_m",
            direction=DIRECTION_LOWER_IS_BETTER,
            observed=0.01,
            draws=MIN_NULL_DRAWS - 1,
            seed=1,
            at_least_as_good=0,
            null_median=1.0,
            null_tail=0.5,
            area=MappedArea(min_xy=(-1.0, -1.0), max_xy=(1.0, 1.0)),
        )


def test_a_statistic_that_passes_but_loses_to_chance_is_uninformative() -> None:
    """The bench's sidewalk row, expressed as a verdict.

    0.00 m against ground truth reads as a pass by any distance rule. The same
    metric scored 0.00 m against a RANDOM map, p=1.00. That is not a result and
    this convention refuses to call it one.
    """

    claim = LocalizationClaim(
        entity_id="sidewalk",
        label="sidewalk",
        place_class=CLASS_REGION,
        measure=LOCALIZATION_INTERIOR,
        statistic="evidence_inside_fraction",
        value=1.0,
        threshold=REGION_EVIDENCE_MAJORITY,
        raw_pass=True,
        null=_null(observed=0.0, at_least_as_good=MIN_NULL_DRAWS),
    )
    assert claim.null.p_value == 1.0
    assert claim.null.beats_null is False
    assert claim.verdict == VERDICT_UNINFORMATIVE
    assert claim.is_pass is False


def test_a_verdict_cannot_be_stamped_onto_a_claim() -> None:
    """``verdict`` is a property, so there is no field to overwrite."""

    claim = LocalizationClaim(
        entity_id="bldg_1",
        label="building",
        place_class=CLASS_OBJECT,
        measure=LOCALIZATION_SURFACE,
        statistic="surface_error_m",
        value=0.01,
        threshold=SURFACE_BUDGET_M,
        raw_pass=True,
        null=_null(at_least_as_good=MIN_NULL_DRAWS),
    )
    assert claim.verdict == VERDICT_UNINFORMATIVE
    with pytest.raises((AttributeError, TypeError)):
        claim.verdict = VERDICT_PASS  # type: ignore[misc]
    assert "verdict" not in {f for f in claim.__dataclass_fields__}


def test_a_failing_statistic_is_fail_whatever_the_null_says() -> None:
    claim = LocalizationClaim(
        entity_id="bldg_1",
        label="building",
        place_class=CLASS_OBJECT,
        measure=LOCALIZATION_SURFACE,
        statistic="surface_error_m",
        value=1.5,
        threshold=SURFACE_BUDGET_M,
        raw_pass=False,
        null=_null(at_least_as_good=0),
    )
    assert claim.null.beats_null is True
    assert claim.verdict == VERDICT_FAIL


def test_every_scored_claim_carries_its_null_and_its_denominators(
    surfaces: dict,
) -> None:
    area = MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0))
    claim = score_near_class(
        entity_id="bldg_1",
        surface=surfaces["bldg_1"],
        answer_xy=(-4.5, 3.97),
        area=area,
        candidate_entries=4,
        draws=MIN_NULL_DRAWS,
        denominators={"frames": 120, "map_entries": 36},
    )
    payload = claim.as_dict()
    assert payload["verdict"] == VERDICT_PASS
    assert payload["null_control"]["draws"] == MIN_NULL_DRAWS
    assert payload["null_control"]["population_size"] == 4
    assert payload["denominators"] == {
        "class_instances": 1,
        "frames": 120,
        "map_entries": 36,
    }
    assert payload["null_control"]["area"]["area_m2"] == pytest.approx(208.0)


def test_a_class_query_lets_the_null_hit_any_instance_of_that_class(
    surfaces: dict,
) -> None:
    """"The building" is six buildings. A null that may only hit one is lenient.

    Same answer, same map size, same seed — only the set of targets the null is
    allowed to land on differs. Widening it to the whole class can only make the
    null do better, so the honest p is the larger one, and a scorer that forgot
    the other five instances would report an answer as more significant than it
    is.
    """

    area = MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0))
    rivals = [surfaces[key] for key in sorted(BUILDING_GEOMS) if key != "bldg_1"]
    kwargs = {
        "entity_id": "bldg_1",
        "surface": surfaces["bldg_1"],
        "answer_xy": (-4.5, 3.97),
        "area": area,
        "candidate_entries": 36,
        "draws": MIN_NULL_DRAWS,
    }
    one_target = score_near_class(**kwargs)  # type: ignore[arg-type]
    whole_class = score_near_class(also_satisfied_by=rivals, **kwargs)  # type: ignore[arg-type]
    assert one_target.denominators["class_instances"] == 1
    assert whole_class.denominators["class_instances"] == len(BUILDING_GEOMS)
    assert whole_class.null.null_median <= one_target.null.null_median
    assert whole_class.null.p_value >= one_target.null.p_value
    # The observed answer is on bldg_1's own facade either way.
    assert whole_class.value == pytest.approx(one_target.value, abs=1e-12)


def test_the_sidewalk_query_accepts_either_strip(surfaces: dict) -> None:
    """Two sidewalk instances; evidence on the south strip is still "the sidewalk"."""

    area = MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0))
    south = [(x / 10.0, -3.0) for x in range(-70, 70)]
    claim = score_inside_class(
        entity_id="sidewalk",
        surface=surfaces["sidewalk"],
        answer_xy=(0.0, -3.0),
        evidence_xy=south,
        area=area,
        also_satisfied_by=[surfaces["sidewalk_south"]],
        draws=MIN_NULL_DRAWS,
    )
    assert claim.denominators["class_instances"] == 2
    assert claim.value == pytest.approx(1.0)
    assert claim.verdict == VERDICT_PASS
    # Without the second strip the same answer is nowhere near the region.
    narrow = score_inside_class(
        entity_id="sidewalk",
        surface=surfaces["sidewalk"],
        answer_xy=(0.0, -3.0),
        evidence_xy=south,
        area=area,
        draws=MIN_NULL_DRAWS,
    )
    assert narrow.value == 0.0
    assert narrow.verdict == VERDICT_FAIL


def test_a_mapped_area_with_no_extent_is_refused() -> None:
    with pytest.raises(SurfaceScoringError, match="no extent"):
        MappedArea(min_xy=(0.0, 0.0), max_xy=(0.0, 1.0))


# ============================ 6. large regions get a discriminating metric


def test_bare_containment_of_a_point_cannot_carry_an_inside_class_claim(
    surfaces: dict,
) -> None:
    """The disclosed flaw, refused at the door.

    An answering entry with no supporting evidence reduces the region rule to
    exactly the containment test the bench proved uninformative, so the scorer
    will not build the claim at all.
    """

    with pytest.raises(SurfaceScoringError, match="supporting points"):
        score_inside_class(
            entity_id="sidewalk",
            surface=surfaces["sidewalk"],
            answer_xy=(0.0, 3.2),
            evidence_xy=[],
            area=MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0)),
            draws=MIN_NULL_DRAWS,
        )


def test_evidence_scattered_over_the_map_does_not_beat_chance(
    surfaces: dict,
) -> None:
    """A map entry "on the sidewalk" whose evidence is everywhere is not on it."""

    import random

    area = MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0))
    rng = random.Random(11)
    scattered = [area.sample(rng) for _ in range(400)]
    claim = score_inside_class(
        entity_id="sidewalk",
        surface=surfaces["sidewalk"],
        answer_xy=(0.0, 3.2),
        evidence_xy=scattered,
        area=area,
        draws=MIN_NULL_DRAWS,
        evidence_cap=400,
    )
    assert claim.denominators["answer_point_contained"] is True
    assert claim.value < REGION_EVIDENCE_MAJORITY
    assert claim.verdict == VERDICT_FAIL


def test_evidence_that_really_lies_on_the_sidewalk_beats_chance(
    surfaces: dict,
) -> None:
    """And the converse, so the metric is not merely strict."""

    import random

    area = MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0))
    rng = random.Random(12)
    on_walk = [(rng.uniform(-8.0, 8.0), rng.uniform(2.3, 4.1)) for _ in range(400)]
    claim = score_inside_class(
        entity_id="sidewalk",
        surface=surfaces["sidewalk"],
        answer_xy=(0.0, 3.2),
        evidence_xy=on_walk,
        area=area,
        draws=MIN_NULL_DRAWS,
        evidence_cap=400,
    )
    assert claim.value == pytest.approx(1.0)
    assert claim.null.p_value < NULL_ALPHA
    assert claim.verdict == VERDICT_PASS


def test_a_contained_answer_with_minority_evidence_fails(surfaces: dict) -> None:
    """Containment alone is explicitly NOT sufficient."""

    on_walk = [(x / 10.0, 3.2) for x in range(-40, 40)]  # 80 points, all inside
    off_walk = [(x / 10.0, 0.5) for x in range(-60, 60)]  # 120 points, all outside
    claim = score_inside_class(
        entity_id="sidewalk",
        surface=surfaces["sidewalk"],
        answer_xy=(0.0, 3.2),
        evidence_xy=on_walk + off_walk,
        area=MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0)),
        draws=MIN_NULL_DRAWS,
    )
    assert interior_contains((0.0, 3.2), surfaces["sidewalk"]) is True
    assert claim.value == pytest.approx(80 / 200)
    assert claim.raw_pass is False
    assert claim.verdict == VERDICT_FAIL


def test_an_answer_outside_the_region_fails_even_with_perfect_evidence(
    surfaces: dict,
) -> None:
    on_walk = [(x / 10.0, 3.2) for x in range(-40, 40)]
    claim = score_inside_class(
        entity_id="sidewalk",
        surface=surfaces["sidewalk"],
        answer_xy=(0.0, 0.0),
        evidence_xy=on_walk,
        area=MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0)),
        draws=MIN_NULL_DRAWS,
    )
    assert claim.denominators["answer_point_contained"] is False
    assert claim.verdict == VERDICT_FAIL


def test_the_evidence_fraction_is_the_plain_thing_it_claims_to_be(
    surfaces: dict,
) -> None:
    points = [(0.0, 3.2), (0.0, 3.5), (0.0, 0.0), (0.0, -5.0)]
    assert evidence_inside_fraction(points, surfaces["sidewalk"]) == pytest.approx(0.5)
    assert evidence_inside_fraction([], surfaces["sidewalk"]) == 0.0


def test_the_dispatcher_refuses_a_claim_it_cannot_qualify(surfaces: dict) -> None:
    area = MappedArea(min_xy=(-8.0, -6.0), max_xy=(8.0, 7.0))
    with pytest.raises(SurfaceScoringError, match="candidate_entries"):
        score_localization(
            entity_id="bldg_1",
            surface=surfaces["bldg_1"],
            answer_xy=(-4.5, 3.97),
            area=area,
        )
    with pytest.raises(SurfaceScoringError, match="evidence points"):
        score_localization(
            entity_id="sidewalk",
            surface=surfaces["sidewalk"],
            answer_xy=(0.0, 3.2),
            area=area,
        )


# ============================ 7. arrival-semantics reconciliation (work item 3)


def test_the_near_goal_region_for_a_building_is_still_built_from_the_centre(
    derived: dict,
) -> None:
    """Changing what a MEASUREMENT is compared to must not move the ROBOT.

    The surface field is graded against; it is not an anchor. The navigator's
    ``near`` band for "the building" is the same centre + circumscribed radius
    band it was before this card, byte for byte.
    """

    import mujoco

    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    _regions, objects = extract_city_semantics(model)
    for item in objects:
        entity_id = str(item["id"])
        expected = object_near_goal_region(
            (float(item["position"][0]), float(item["position"][1])),
            float(item["metadata"]["radius_m"]),
            label=str(item["label"]),
            entity_id=entity_id,
        ).as_dict()
        assert item["metadata"]["goal_region"] == expected, entity_id
        if entity_id in BUILDING_GEOMS:
            centre, _half = BUILDING_GEOMS[entity_id]
            assert expected["center"] == [centre[0], centre[1]]


def test_go_to_the_building_stops_in_front_of_the_facade_it_can_see(
    surfaces: dict,
) -> None:
    """What the owner means by "go to the building", made measurable.

    For every point on the ``near`` band the navigator would accept as arrival:

    * it is OUTSIDE the building footprint (the robot never ends up in the block);
    * it clears the nearest surface by at least the scene's own
      ``target_min_surface_clearance_m``, read from the metadata rather than
      re-typed;
    * standing there and looking at the building, the face it sees is a real
      face of that building — i.e. the thing perception is graded against is the
      thing the robot is actually looking at.

    That is the reconciliation the card asks for: the facade is the measurement
    target AND the thing at the end of the approach, without the facade ever
    becoming the goal anchor.
    """

    import math

    import mujoco

    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    _regions, objects = extract_city_semantics(model)
    by_id = {str(item["id"]): item for item in objects}

    for entity_id in sorted(BUILDING_GEOMS):
        item = by_id[entity_id]
        metadata = item["metadata"]
        clearance = float(metadata["target_min_surface_clearance_m"])
        band = metadata["goal_region"]["band_m"]
        centre = (float(item["position"][0]), float(item["position"][1]))
        surface = surfaces[entity_id]
        polygon = surface["parts"][0]["polygon"]

        for step in range(72):
            angle = 2.0 * math.pi * step / 72.0
            for radius in (float(band[0]), float(band[1])):
                point = (
                    centre[0] + radius * math.cos(angle),
                    centre[1] + radius * math.sin(angle),
                )
                from evals.nav_instruct.surface_scoring import polygon_contains

                assert not polygon_contains(point, polygon), (entity_id, point)
                assert surface_error_m(point, surface) >= clearance, (entity_id, point)
                faces = visible_facade(surface, point)
                assert faces, (entity_id, point)
                assert all(face["geom"] == entity_id for face in faces)


def test_an_approach_from_the_street_sees_the_street_facing_face(
    surfaces: dict,
) -> None:
    """The specific claim the bench's 6/6 rests on, stated as geometry."""

    for entity_id, (centre, half) in sorted(BUILDING_GEOMS.items()):
        face_y = _visible_face_y(centre, half)
        # Stand on the street side, 3 m out from the visible face.
        observer = (centre[0], face_y - 3.0 if centre[1] > 0 else face_y + 3.0)
        faces = visible_facade(surfaces[entity_id], observer)
        midpoints_y = [face["midpoint"][1] for face in faces]
        assert pytest.approx(face_y, abs=1e-9) in midpoints_y, entity_id


def test_the_surface_convention_never_reaches_the_navigator() -> None:
    """No module on the robot's control path imports the scoring helper.

    The card's smallest-touch constraint, expressed as something that reddens.
    ``arrival_semantics`` gained one FIELD; if any src module ever starts
    importing the eval scorer, that is a control-path dependency on an answer
    key and it must be a deliberate decision, not a drift.
    """

    import re
    from pathlib import Path

    #: An IMPORT, not a mention: ``arrival_semantics`` names the scorer in prose
    #: so a reader finds it, and prose is not a dependency.
    importer = re.compile(
        r"^\s*(?:from\s+\S*surface_scoring|import\s+\S*surface_scoring)", re.MULTILINE
    )
    src = Path(__file__).resolve().parents[1] / "src" / "parcel_robot"
    offenders = [
        path.relative_to(src).as_posix()
        for path in src.rglob("*.py")
        if importer.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders


def test_the_scene_truth_module_still_derives_the_old_tables_unchanged(
    derived: dict,
) -> None:
    """Belt and braces: adding surfaces moved nothing in ``derived``."""

    assert derive_scene_truth() == derived
