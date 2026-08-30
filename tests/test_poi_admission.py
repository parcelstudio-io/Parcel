"""Card C1 (POI-ORACLE-1), follow-up F1 — the demo POI table answers only on the
scene it was surveyed on.

NAV-GEN-1 measured the defect on 30 generated scenes: 90/90 "go to the
crosswalk" episodes ground to ``crosswalk_a`` at ``(3.5, -0.6)``, a coordinate
that lives in ``configs/navigation/cities/demo_pois.yaml`` and is a fact about
one scene only; 42 of them declare ``arrived`` with the body in no crosswalk at
all (``research/20260829/nav-gen-attribution-1/RESULTS.md`` §5.3).

**Admission is IDENTITY** (F1 ruling): the table declares ``scene_id:
parcel_city_block`` — the MJCF ``model`` name of ``scenes/city_block.xml`` —
and a POI may answer only while that scene is the loaded one. No scene loaded
is a refusal too: a real robot under the oracle source must never be answered
by the demo table.

The geometry is kept only as a diagnostic, and generated seed 880027 is exactly
why. Its crosswalk polygon CONTAINS ``(3.5, -0.6)``:

===================================  ==========================  =========
scene                                distance from (3.5, -0.6)   admitted
===================================  ==========================  =========
demo block (``city_block.xml``)      0.200 m (POI is outside)    yes
generated 880000                     2.408 m                     no
generated 880027                     0.000 m (POI is inside)     **no**
===================================  ==========================  =========

880027's containment is a coincidence of a procedural sampler — it does not
make "crosswalk near coffee, 42nd street" a place on that seed. C1's first cut
admitted it on that geometry and the NAV-GEN-1 rows showed the cost: the
coincidence-admitted episodes carried every remaining false arrival. Under F1
it is REFUSED, and ``geometry_backed is True`` on the refusal records that the
scene's own crosswalk was near the coordinate anyway.
"""

from __future__ import annotations

from pathlib import Path

import mujoco
import pytest

from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.poi_admission import (
    DIAGNOSTIC_BAND_M,
    OUTCOME_ADMITTED,
    OUTCOME_NO_SCENE,
    OUTCOME_SCENE_MISMATCH,
    PoiRefused,
    active_scene_instances,
    admit_poi,
    clear_scene_instances,
    geometry_diagnostic,
    ground_admitted_poi,
    poi_lookup_metadata,
    publish_scene_semantics,
    scene_id_from_model,
    scene_instances_from_specs,
)
from parcel_robot.perception.city_semantics import extract_city_semantics
from parcel_robot.simulation.headless_city import DEFAULT_CITY_SCENE, HeadlessCityWorld

#: The row ``demo_pois.yaml`` ships, verbatim in the fields admission reads.
CROSSWALK_POI = {
    "id": "crosswalk_a",
    "names": ["crosswalk", "crosswalk near coffee"],
    "street": "42nd street",
    "category": "crosswalk",
    "position": [3.5, -0.6, 0.0],
}
COFFEE_POI = {
    "id": "coffee_42nd",
    "names": ["coffee shop at 42nd street", "coffee shop"],
    "street": "42nd street",
    "category": "cafe",
    "position": [42.0, 8.5, 0.0],
}

CROSSWALK_DIRECTIVE = "go to the crosswalk"
#: The MJCF ``model`` name of ``scenes/city_block.xml`` and the value
#: ``demo_pois.yaml`` declares. The test below pins them equal.
DEMO_SCENE_ID = "parcel_city_block"
POI_TABLE = Path(__file__).resolve().parents[1] / "configs/navigation/cities/demo_pois.yaml"


@pytest.fixture(autouse=True)
def _no_published_scene():
    """The seam is process-scoped; a test that leaks it lies for the next one."""

    clear_scene_instances()
    yield
    clear_scene_instances()


@pytest.fixture(scope="module")
def generated_scene(tmp_path_factory) -> dict[int, Path]:
    """NAV-GEN-1's own scenes, built by the eval generator, not hand-written.

    The emitted MJCF includes the Go2 model as ``../../../third_party/...``, so
    the scenes are written three levels under a root that carries a symlink to
    the repo's — the same tree ``model-a-stream-1/teacher.py`` builds, kept in
    pytest's own scratch so nothing is written into the repo.
    """

    from evals.nav_instruct.scene_gen import build_scene

    root = tmp_path_factory.mktemp("c1_scenes")
    (root / "third_party").symlink_to(Path(__file__).resolve().parents[1] / "third_party")
    scene_dir = root / "configs" / "scenes" / "generated"
    scene_dir.mkdir(parents=True)
    built: dict[int, Path] = {}
    for seed in (880000, 880027):
        _params, xml, _derived, _record = build_scene(seed, scratch_dir=scene_dir)
        path = scene_dir / f"generated_{seed}.xml"
        path.write_text(xml, encoding="utf-8")
        built[seed] = path
    return built


def _publish(scene: Path):
    """Publish a scene exactly as the product does — through the extractor."""

    model = mujoco.MjModel.from_xml_path(str(scene))
    regions, objects = extract_city_semantics(model)
    published = active_scene_instances()
    assert published is not None, "extract_city_semantics publishes the loaded scene"
    assert published.scene_id == scene_id_from_model(model)
    assert published.instances == scene_instances_from_specs(regions, objects)
    return published


def _crosswalk_distance(scene) -> float:
    crosswalk = [item for item in scene.instances if item.label == "crosswalk"]
    assert crosswalk, "every scene under test declares a crosswalk"
    return min(item.distance_to_arrival_geometry(3.5, -0.6) for item in crosswalk)


# ---------------------------------------------------------------------------
# The admission rule: scene identity.
# ---------------------------------------------------------------------------


def test_the_shipped_table_declares_the_scene_its_coordinates_live_on() -> None:
    """The YAML key and the scene's own MJCF name must be the same string."""

    import yaml

    from parcel_robot.navigation.grounder import PlaceGrounder

    declared = yaml.safe_load(POI_TABLE.read_text(encoding="utf-8"))["scene_id"]
    loaded = scene_id_from_model(mujoco.MjModel.from_xml_path(str(DEFAULT_CITY_SCENE)))

    assert declared == loaded == DEMO_SCENE_ID
    assert PlaceGrounder.from_yaml(POI_TABLE).scene_id == DEMO_SCENE_ID


@pytest.mark.parametrize(
    ("seed", "expected_outcome", "expected_scene_id", "geometry_would_back"),
    [
        pytest.param(None, OUTCOME_ADMITTED, DEMO_SCENE_ID, True, id="demo-block-admits"),
        pytest.param(
            880000,
            OUTCOME_SCENE_MISMATCH,
            "parcel_val_unseen_880000",
            False,
            id="generated-mismatch",
        ),
        pytest.param(
            880027,
            OUTCOME_SCENE_MISMATCH,
            "parcel_val_unseen_880027",
            True,
            id="generated-that-contains-the-coordinate-STILL-refuses",
        ),
    ],
)
def test_crosswalk_poi_admission_per_scene(
    generated_scene, seed, expected_outcome, expected_scene_id, geometry_would_back
) -> None:
    """880027 is the flipped row: its crosswalk polygon CONTAINS (3.5, -0.6).

    C1's first cut admitted it on that geometry. Under F1 a coincidence of the
    procedural sampler is not a reason for the demo table to answer, so the
    outcome is ``scene_mismatch`` — and the diagnostic still says the geometry
    would have backed it, which is the evidence that the demotion is real.
    """

    scene = _publish(DEFAULT_CITY_SCENE if seed is None else generated_scene[seed])
    admission = admit_poi(CROSSWALK_POI, scene=scene, declared_scene_id=DEMO_SCENE_ID)

    assert scene.scene_id == expected_scene_id
    assert admission.outcome == expected_outcome
    assert admission.admitted is (expected_outcome == OUTCOME_ADMITTED)
    assert admission.loaded_scene_id == expected_scene_id
    assert admission.declared_scene_id == DEMO_SCENE_ID
    # The geometric predicate is computed and reported — never consulted.
    assert admission.geometry_backed is geometry_would_back
    assert admission.nearest_instance_id == "crosswalk"
    if expected_outcome is OUTCOME_SCENE_MISMATCH:
        assert admission.reason == f"scene_mismatch:{expected_scene_id}/{DEMO_SCENE_ID}"
    else:
        assert admission.reason == ""


def test_no_published_scene_is_a_refusal() -> None:
    """A real robot under the oracle source is never answered by the demo table."""

    assert active_scene_instances() is None
    admission = admit_poi(CROSSWALK_POI, scene=None, declared_scene_id=DEMO_SCENE_ID)

    assert (admission.admitted, admission.outcome, admission.reason) == (
        False,
        OUTCOME_NO_SCENE,
        "no_scene",
    )
    assert admission.declared_scene_id == DEMO_SCENE_ID


def test_a_table_that_declares_no_scene_matches_nothing() -> None:
    """Undeclared coordinates cannot be checked, so they are refused."""

    scene = _publish(DEFAULT_CITY_SCENE)
    admission = admit_poi(CROSSWALK_POI, scene=scene, declared_scene_id="")

    assert admission.admitted is False
    assert admission.outcome == OUTCOME_SCENE_MISMATCH
    assert admission.reason == f"scene_mismatch:{DEMO_SCENE_ID}/"


def test_geometry_is_a_diagnostic_and_disagrees_with_admission(generated_scene) -> None:
    """The one case that proves the demotion: geometry says yes, identity says no."""

    contains = _publish(generated_scene[880027])
    assert _crosswalk_distance(contains) == pytest.approx(0.000, abs=5e-3)
    backed, instance_id, distance = geometry_diagnostic(CROSSWALK_POI, contains)
    assert (backed, instance_id) == (True, "crosswalk")
    assert distance == pytest.approx(0.0, abs=1e-9)
    assert admit_poi(CROSSWALK_POI, scene=contains, declared_scene_id=DEMO_SCENE_ID).admitted is (
        False
    )

    far = _publish(generated_scene[880000])
    assert _crosswalk_distance(far) == pytest.approx(2.408, abs=5e-3)
    assert geometry_diagnostic(CROSSWALK_POI, far)[0] is False

    # The demo block's own crosswalk is 0.20 m from the coordinate — the POI is
    # OUTSIDE it — which is why the first cut needed the 0.32 m body band and
    # why no distance rule could separate the demo block from 880027.
    demo = _publish(DEFAULT_CITY_SCENE)
    assert _crosswalk_distance(demo) == pytest.approx(0.200, abs=5e-3)
    assert DIAGNOSTIC_BAND_M == pytest.approx(0.32)

    # A class no city scene models has no diagnostic at all, and identity still
    # decides: the cafe is refused off its own scene.
    assert geometry_diagnostic(COFFEE_POI, far) == (None, "", None)
    assert admit_poi(COFFEE_POI, scene=far, declared_scene_id=DEMO_SCENE_ID).admitted is False


def test_publishing_the_same_specs_twice_is_an_identity_check() -> None:
    model = mujoco.MjModel.from_xml_path(str(DEFAULT_CITY_SCENE))
    regions, objects = extract_city_semantics(model)
    first = publish_scene_semantics(regions, objects, scene_id=DEMO_SCENE_ID)

    assert publish_scene_semantics(regions, objects, scene_id=DEMO_SCENE_ID) is first
    assert publish_scene_semantics(list(regions), objects, scene_id=DEMO_SCENE_ID) is not first
    assert publish_scene_semantics(regions, objects, scene_id="other_scene").scene_id == (
        "other_scene"
    )


def test_object_instances_carry_their_declared_goal_band() -> None:
    """The diagnostic reads the annulus K0 already arrives on, never its own."""

    regions, objects = extract_city_semantics(
        mujoco.MjModel.from_xml_path(str(DEFAULT_CITY_SCENE))
    )
    instances = {item.instance_id: item for item in scene_instances_from_specs(regions, objects)}
    bench = instances["bench_1"]

    assert bench.label == "bench"
    assert bench.band_m is not None and bench.band_m[1] > bench.band_m[0] >= 0.0
    assert bench.center is not None
    assert bench.distance_to_arrival_geometry(*bench.center) == pytest.approx(
        bench.band_m[0], abs=1e-9
    )


# ---------------------------------------------------------------------------
# The product caller: DirectiveNavigator.parse, with a venue that loaded a scene.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seed", "expects_poi"),
    [
        pytest.param(None, True, id="demo-block-keeps-known_poi"),
        pytest.param(880000, False, id="generated-refuses"),
        pytest.param(880027, False, id="generated-that-contains-it-ALSO-refuses"),
    ],
)
def test_parse_grounds_or_refuses_by_scene(generated_scene, seed, expects_poi) -> None:
    scene = _publish(DEFAULT_CITY_SCENE if seed is None else generated_scene[seed])
    navigator = DirectiveNavigator.from_config()
    try:
        mission = navigator.parse(CROSSWALK_DIRECTIVE)
    finally:
        navigator.close()

    if expects_poi:
        assert mission.metadata["goal_source"] == "known_poi"
        assert mission.goal is not None and mission.goal.poi_id == "crosswalk_a"
        assert "poi_refused" not in mission.metadata
    else:
        assert mission.metadata["goal_source"] == "semantic_search"
        assert mission.goal is None
        assert mission.semantic_goal is not None
        assert mission.metadata["poi_refused"] == (
            f"scene_mismatch:{scene.scene_id}/{DEMO_SCENE_ID}"
        )


def test_parse_refuses_the_table_when_no_venue_loaded_a_scene() -> None:
    """F1 requirement 3, on the product caller."""

    navigator = DirectiveNavigator.from_config()
    try:
        mission = navigator.parse(CROSSWALK_DIRECTIVE)
        unrelated = navigator.parse("go to the nearest lamppost")
    finally:
        navigator.close()

    assert mission.metadata["goal_source"] == "semantic_search"
    assert mission.goal is None
    assert mission.metadata["poi_refused"] == "no_scene"
    # "the directive named no POI at all" stays untagged — three distinct facts.
    assert unrelated.metadata["goal_source"] == "semantic_search"
    assert "poi_refused" not in unrelated.metadata
    assert "poi_grounding_disabled" not in unrelated.metadata


def test_all_four_demo_pois_refuse_on_a_generated_scene(generated_scene) -> None:
    """The whole table is facts about one block, not just the crosswalk row."""

    _publish(generated_scene[880000])
    navigator = DirectiveNavigator.from_config()
    try:
        missions = {
            directive: navigator.parse(directive)
            for directive in (
                "go to the coffee shop",
                "go to the bookstore",
                "go to the park",
                CROSSWALK_DIRECTIVE,
            )
        }
    finally:
        navigator.close()

    for directive, mission in missions.items():
        assert mission.goal is None, directive
        assert mission.metadata["goal_source"] == "semantic_search", directive
        assert mission.metadata["poi_refused"] == (
            f"scene_mismatch:parcel_val_unseen_880000/{DEMO_SCENE_ID}"
        ), directive


def test_the_driving_venue_publishes_its_own_scene_identity(generated_scene) -> None:
    """The hook is the venue's: build a world, get its scene and its id.

    ``HeadlessCityWorld.__init__`` extracts the scene's semantics before any
    navigator exists, which is what makes the decision available at ``parse``
    time, where no observation has arrived yet.
    """

    assert active_scene_instances() is None
    world = HeadlessCityWorld(generated_scene[880000])
    published = active_scene_instances()

    assert published is not None
    assert published.scene_id == "parcel_val_unseen_880000"
    assert "crosswalk" in published.instance_ids()

    navigator = DirectiveNavigator.from_config()
    try:
        mission = navigator.parse(CROSSWALK_DIRECTIVE)
    finally:
        navigator.close()
        world.stop()
    assert mission.metadata["goal_source"] == "semantic_search"
    assert mission.metadata["poi_refused"].startswith("scene_mismatch:")

    demo = HeadlessCityWorld()
    assert active_scene_instances().scene_id == DEMO_SCENE_ID
    navigator = DirectiveNavigator.from_config()
    try:
        mission = navigator.parse(CROSSWALK_DIRECTIVE)
    finally:
        navigator.close()
        demo.stop()
    assert mission.metadata["goal_source"] == "known_poi"


# ---------------------------------------------------------------------------
# The reasons: three different facts, three different metadata shapes.
# ---------------------------------------------------------------------------


def test_refusal_and_disabled_and_not_a_poi_are_told_apart(generated_scene) -> None:
    from parcel_robot.navigation.grounder import PlaceGrounder

    _publish(generated_scene[880000])
    grounder = PlaceGrounder([dict(CROSSWALK_POI)], scene_id=DEMO_SCENE_ID)

    with pytest.raises(PoiRefused) as refused:
        ground_admitted_poi(grounder, CROSSWALK_DIRECTIVE)
    assert refused.value.poi_id == "crosswalk_a"
    assert refused.value.admission.outcome == OUTCOME_SCENE_MISMATCH
    assert isinstance(refused.value, LookupError)
    assert poi_lookup_metadata(grounder, refused.value) == {
        "poi_refused": f"scene_mismatch:parcel_val_unseen_880000/{DEMO_SCENE_ID}"
    }

    with pytest.raises(LookupError) as absent:
        ground_admitted_poi(grounder, "go to the bench")
    assert poi_lookup_metadata(grounder, absent.value) == {}

    disabled = PlaceGrounder.disabled("card C-3 REVISION 1: off-oracle")
    with pytest.raises(LookupError) as off_oracle:
        ground_admitted_poi(disabled, CROSSWALK_DIRECTIVE)
    assert poi_lookup_metadata(disabled, off_oracle.value) == {
        "poi_grounding_disabled": "card C-3 REVISION 1: off-oracle"
    }


def test_a_grounder_that_predates_this_card_declares_no_scene_and_is_refused(
    generated_scene,
) -> None:
    """The BARN-bundle shape: no ``scene_id``, so nothing can vouch for it."""

    _publish(generated_scene[880027])

    class _BundleGrounder:
        """No ``scene_id``, no ``pois`` — exactly the frozen bundle's copy."""

        def ground(self, directive: str):
            from parcel_robot.navigation.base import GoalPose

            return GoalPose(x=3.5, y=-0.6, z=0.0, poi_id="crosswalk_a", label="crosswalk")

    with pytest.raises(PoiRefused) as refused:
        ground_admitted_poi(_BundleGrounder(), CROSSWALK_DIRECTIVE)
    assert refused.value.admission.reason == "scene_mismatch:parcel_val_unseen_880027/"


def test_the_eval_and_panel_runner_path_keeps_known_poi() -> None:
    """F1 addendum 4 — the RED/GREEN pair, one second, on the product callers.

    RED: with no venue having loaded a scene, ``parse`` refuses with
    ``no_scene`` — which is CORRECT for a real robot under the oracle source,
    and was the state ``evals.nav_instruct``'s runner and
    ``scripts/mutation_panel.py`` would execute in if the identity were
    published per caller instead of in the loader.

    GREEN: the eval/panel runner constructs ``NavInstructRunner``, whose
    ``HeadlessCityWorld`` reads the demo block through
    ``extract_city_semantics`` — the loader, which publishes — so the same call
    grounds through the table again. The frozen ``nav-region_goal-*``
    "go to the crosswalk" episodes depend on exactly this.
    """

    navigator = DirectiveNavigator.from_config()
    try:
        red = navigator.parse(CROSSWALK_DIRECTIVE)
    finally:
        navigator.close()
    assert red.metadata["goal_source"] == "semantic_search"
    assert red.metadata["poi_refused"] == "no_scene"

    from evals.nav_instruct.runner import NavInstructRunner

    runner = NavInstructRunner(max_steps=1)
    try:
        published = active_scene_instances()
        assert published is not None and published.scene_id == DEMO_SCENE_ID
        green = DirectiveNavigator.from_config().parse(CROSSWALK_DIRECTIVE)
    finally:
        runner.world.stop()
    assert green.metadata["goal_source"] == "known_poi"
    assert green.goal is not None and green.goal.poi_id == "crosswalk_a"
    assert green.metadata.get("poi_refused") is None


def test_no_scene_and_scene_mismatch_stay_distinct_reasons(generated_scene) -> None:
    """F1 addendum 4: they are different facts and keep different tokens."""

    navigator = DirectiveNavigator.from_config()
    try:
        assert navigator.parse(CROSSWALK_DIRECTIVE).metadata["poi_refused"] == "no_scene"
        _publish(generated_scene[880000])
        assert navigator.parse(CROSSWALK_DIRECTIVE).metadata["poi_refused"] == (
            f"scene_mismatch:parcel_val_unseen_880000/{DEMO_SCENE_ID}"
        )
        _publish(DEFAULT_CITY_SCENE)
        assert navigator.parse(CROSSWALK_DIRECTIVE).metadata["goal_source"] == "known_poi"
    finally:
        navigator.close()
