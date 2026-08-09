"""Per-scene semantics sidecar: bit-equality with the retired literals, and fail-closed.

The bit-equality tests are the whole point of the migration. Wave 0 (card W0-D)
found that a hand-transcribed table had silently disagreed with the scene in
seven fields for the entire life of the NAV_INSTRUCT harness. Deriving the
class/alias/prefix tables from a sidecar is only an improvement if the derived
tables are *proven* identical to what they replaced, so the literals that used
to live in ``city_semantics.py`` are pinned here verbatim.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    next_to_band_from_centre,
    next_to_band_surface_slack_m,
    next_to_is_achievable,
)
from parcel_robot.navigation.attributes import SIZE_METADATA_KEYS
from parcel_robot.navigation.relation_registry import RELATIONS, RelationAnchor
from parcel_robot.scene_semantics import (
    DEFAULT_SIDECAR,
    LANDMARK_ROLES,
    SceneSemanticsError,
    load_scene_semantics,
    parse_scene_semantics,
    scene_semantics,
)

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / DEFAULT_SIDECAR

# --- the literals this sidecar replaced, copied verbatim from the pre-migration
# --- city_semantics.py (git blame anchor: "Vocabulary table (prefix → class)").
RETIRED_OBJECT_PREFIX_TABLE = (
    ("lamp_post_", "lamppost"),
    ("bench_", "bench"),
    ("tree_top_", "tree"),
    ("tree_", "tree"),
    ("planter_", "planter"),
    ("bldg_", "building"),
)
RETIRED_REGION_PREFIX_TABLE = (
    ("sidewalk", "sidewalk"),
    ("xw", "crosswalk"),
    ("crosswalk", "crosswalk"),
)
RETIRED_CLASS_ALIASES = {
    "lamppost": ("lamp post", "streetlight", "street light", "lamp"),
    "bench": ("seat", "park bench", "bench seat"),
    "tree": ("trees", "street tree"),
    "planter": ("plant pot", "flower box", "pot"),
    "building": ("bldg", "storefront", "building face"),
    "sidewalk": ("pavement", "safe region"),
    "crosswalk": ("crossing", "zebra crossing", "cross walk"),
}


def _raw() -> dict:
    return yaml.safe_load(SIDECAR.read_text(encoding="utf-8"))


# --- bit-equality ----------------------------------------------------------


def test_sidecar_reproduces_the_retired_object_prefix_table_exactly() -> None:
    from parcel_robot import city_semantics

    assert city_semantics.OBJECT_PREFIX_TABLE == RETIRED_OBJECT_PREFIX_TABLE
    assert load_scene_semantics(SIDECAR).object_prefix_table() == RETIRED_OBJECT_PREFIX_TABLE


def test_sidecar_reproduces_the_retired_region_prefix_table_exactly() -> None:
    from parcel_robot import city_semantics

    assert city_semantics.REGION_PREFIX_TABLE == RETIRED_REGION_PREFIX_TABLE
    assert load_scene_semantics(SIDECAR).region_prefix_table() == RETIRED_REGION_PREFIX_TABLE


def test_sidecar_reproduces_the_retired_alias_table_exactly() -> None:
    from parcel_robot import city_semantics

    assert city_semantics.CLASS_ALIASES == RETIRED_CLASS_ALIASES
    assert city_semantics.vocabulary_aliases() == RETIRED_CLASS_ALIASES
    assert load_scene_semantics(SIDECAR).alias_table() == RETIRED_CLASS_ALIASES
    # Order matters too: the alias table is iterated when building metadata.
    assert list(city_semantics.CLASS_ALIASES) == list(RETIRED_CLASS_ALIASES)


def test_instance_label_lookup_is_no_longer_a_second_copy_of_the_prefix_table() -> None:
    """``_label_for_instance`` used to repeat the table by hand."""

    from parcel_robot import city_semantics

    expected = {
        "lamp_post_1": "lamppost",
        "lamp_post_2": "lamppost",
        "bench_1": "bench",
        "tree_1": "tree",
        "tree_2": "tree",
        "planter_1": "planter",
        "bldg_3": "building",
        "hydrant_9": "object",
    }
    for instance_id, label in expected.items():
        assert city_semantics._label_for_instance(instance_id) == label


def test_extraction_is_bit_identical_to_the_retired_literals() -> None:
    """The whole-output equality commit, not just the tables.

    Proving the three tables match is necessary but not sufficient: the tables
    feed ``extract_city_semantics``, whose output (positions, radii, polygons,
    goal-region metadata, key order) is what every grounder and scorer reads.
    This re-extracts the real city scene twice — once with the derived tables,
    once with the literals monkeypatched back in, including the hand-written
    ``_label_for_instance`` chain — and compares the serialized result.
    """

    import json

    import mujoco

    from parcel_robot import city_semantics

    def retired_label_for_instance(instance_id: str) -> str:
        if instance_id.startswith("lamp_post_"):
            return "lamppost"
        if instance_id.startswith("bench_"):
            return "bench"
        if instance_id.startswith("tree_"):
            return "tree"
        if instance_id.startswith("planter_"):
            return "planter"
        if instance_id.startswith("bldg_"):
            return "building"
        return "object"

    model = mujoco.MjModel.from_xml_path(
        str(REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml")
    )
    derived = json.dumps(city_semantics.extract_city_semantics(model))

    saved = (
        city_semantics.OBJECT_PREFIX_TABLE,
        city_semantics.REGION_PREFIX_TABLE,
        city_semantics.CLASS_ALIASES,
        city_semantics.CLASS_ATTRIBUTE_METADATA,
        city_semantics._label_for_instance,
    )
    try:
        city_semantics.OBJECT_PREFIX_TABLE = RETIRED_OBJECT_PREFIX_TABLE
        city_semantics.REGION_PREFIX_TABLE = RETIRED_REGION_PREFIX_TABLE
        city_semantics.CLASS_ALIASES = RETIRED_CLASS_ALIASES
        city_semantics.CLASS_ATTRIBUTE_METADATA = {}
        city_semantics._label_for_instance = retired_label_for_instance
        retired = json.dumps(city_semantics.extract_city_semantics(model))
    finally:
        (
            city_semantics.OBJECT_PREFIX_TABLE,
            city_semantics.REGION_PREFIX_TABLE,
            city_semantics.CLASS_ALIASES,
            city_semantics.CLASS_ATTRIBUTE_METADATA,
            city_semantics._label_for_instance,
        ) = saved

    assert derived == retired


def test_no_class_declares_attribute_metadata_yet_so_extraction_is_unchanged() -> None:
    """The seam exists; nothing rides it, which is why bit-equality holds."""

    from parcel_robot import city_semantics

    assert all(not values for values in city_semantics.CLASS_ATTRIBUTE_METADATA.values())


# --- fail-closed validation ------------------------------------------------


def test_unknown_top_level_key_is_rejected() -> None:
    data = _raw()
    data["extra_knob"] = True
    with pytest.raises(SceneSemanticsError, match="unknown=\\['extra_knob'\\]"):
        parse_scene_semantics(data)


def test_unknown_class_key_is_rejected() -> None:
    data = _raw()
    data["classes"]["bench"]["colour"] = "brown"
    with pytest.raises(SceneSemanticsError, match="unknown=\\['colour'\\]"):
        parse_scene_semantics(data)


def test_an_affordance_that_is_not_a_registered_relation_is_rejected() -> None:
    data = _raw()
    data["classes"]["bench"]["affordances"].append("teleport_to")
    with pytest.raises(SceneSemanticsError, match="not a registered relation"):
        parse_scene_semantics(data)


def test_an_affordance_whose_anchor_kind_is_wrong_is_rejected() -> None:
    data = _raw()
    # `inside` only accepts a region anchor; the bench is an object.
    data["classes"]["bench"]["affordances"].append("inside")
    with pytest.raises(SceneSemanticsError, match="does not\\s+accept a object anchor"):
        parse_scene_semantics(data)


def test_a_landmark_role_outside_the_closed_vocabulary_is_rejected() -> None:
    data = _raw()
    data["classes"]["tree"]["landmark_roles"].append("photogenic")
    with pytest.raises(SceneSemanticsError, match="outside the closed vocabulary"):
        parse_scene_semantics(data)


def test_attribute_metadata_keys_must_be_readable_by_the_attribute_matcher() -> None:
    data = _raw()
    data["classes"]["tree"]["metadata"] = {"girth_m": 0.4}
    with pytest.raises(SceneSemanticsError, match="not readable by the attribute matcher"):
        parse_scene_semantics(data)
    # …and a key the matcher does read is accepted.
    data["classes"]["tree"]["metadata"] = {SIZE_METADATA_KEYS[-1]: 3.0}
    parsed = parse_scene_semantics(data)
    assert parsed.get("tree").metadata_dict() == {SIZE_METADATA_KEYS[-1]: 3.0}


def test_prefix_ordering_that_would_shadow_a_longer_prefix_is_rejected() -> None:
    """The ``tree_top_`` comment becomes an enforced rule."""

    data = _raw()
    prefixes = data["geom_prefixes"]
    top = next(item for item in prefixes if item["prefix"] == "tree_top_")
    prefixes.remove(top)
    prefixes.append(top)  # now `tree_` precedes `tree_top_`
    with pytest.raises(SceneSemanticsError, match="ordering is unsafe"):
        parse_scene_semantics(data)


def test_a_prefix_naming_an_undeclared_class_is_rejected() -> None:
    data = _raw()
    data["geom_prefixes"].append({"prefix": "hydrant_", "class": "hydrant"})
    with pytest.raises(SceneSemanticsError, match="undeclared class"):
        parse_scene_semantics(data)


def test_a_class_no_prefix_can_ever_match_is_rejected() -> None:
    data = _raw()
    data["classes"]["fountain"] = {
        "kind": "object",
        "aliases": [],
        "affordances": ["near"],
        "landmark_roles": ["waypoint"],
        "size": {"source": "geom_radius_m", "note": "not in the scene"},
        "metadata": {},
    }
    with pytest.raises(SceneSemanticsError, match="no geom prefix"):
        parse_scene_semantics(data)


def test_schema_version_is_pinned() -> None:
    data = _raw()
    data["schema_version"] = 2
    with pytest.raises(SceneSemanticsError, match="schema_version must be 1"):
        parse_scene_semantics(data)


# --- derived views ---------------------------------------------------------


def test_declared_affordances_are_achievable_at_the_scene_s_real_radii() -> None:
    """An advertised relation must be reachable *under the stand-off envelope*.

    **Strengthened 2026-08-08 (card B-2).** It used to test only that the goal
    region was a non-empty *set of points* — ``max(band_lo, footprint) <=
    band_hi`` — which is a statement about the band and the anchor radius and
    says nothing about whether a **body** can stand in it. It passed ``bench``
    (r = 0.734), ``tree`` (0.58) and ``planter`` (0.45) for the whole life of
    the sidecar, and at the time all three were impossible: the band was
    measured to the anchor's *centre* while every stand-off authority is
    measured to its *surface*, so a pose at the band's outer edge sat
    ``band_hi - r`` from the surface and had to clear
    ``StandOffEnvelope.minimum_vicinity(r)``.

    **The band was re-anchored to the surface on 2026-08-09 (card S-1)**, which
    is why bench/tree/planter advertise ``next_to`` again. The check stays
    exactly as strong: it still asks the authority itself
    (:func:`next_to_is_achievable`) rather than asking whether a point set is
    non-empty, and it would still fail loudly if a class advertised a placement
    this body could not hold.
    """

    truth = json.loads((REPO / "evals/nav_instruct/scene_truth.json").read_text())["derived"]
    semantics = load_scene_semantics(SIDECAR)
    checked = 0
    for entity_id, entity in truth.items():
        scene_class = semantics.get(entity["label"])
        for relation in scene_class.affordances:
            spec = RELATIONS.get(relation)
            if not spec.has_goal_region:
                continue
            if entity["kind"] == "region":
                anchor = RelationAnchor(
                    kind="region",
                    polygon=tuple(tuple(p) for p in entity["polygon"]),
                )
            else:
                anchor = RelationAnchor(
                    kind="object",
                    center=tuple(entity["position"]),
                    radius_m=float(entity["radius_m"]),
                    label=entity["label"],
                )
            region = spec.goal_region(anchor)
            if region.kind == "relative_band":
                assert region.band_m is not None
                lo = max(region.band_m[0], region.anchor_footprint_m)
                assert lo <= region.band_m[1], (
                    f"{entity['label']} advertises {relation!r} but its goal region is "
                    f"empty at radius {entity['radius_m']}"
                )
            if relation == "next_to" and entity["kind"] == "object":
                radius = float(entity["radius_m"])
                assert next_to_is_achievable(radius), (
                    f"{entity['label']} ({entity_id}, r={radius:.4f} m) advertises "
                    f"'next_to', but the band's outer edge "
                    f"{next_to_band_from_centre(radius)[1]:.4f} m is inside the "
                    f"stand-off envelope's minimum_vicinity({radius:.4f}) = "
                    f"{DEFAULT_STAND_OFF_ENVELOPE.minimum_vicinity(radius):.4f} m. "
                    f"No body can stand in that band. The band leaves "
                    f"{next_to_band_surface_slack_m():.2f} m of usable width "
                    f"around an anchor of any size"
                )
            checked += 1
    assert checked > 0


def test_next_to_achievability_no_longer_depends_on_the_anchor_s_size() -> None:
    """What surface-anchoring the band did to the derivation, stated exactly.

    Until 2026-08-09 this test pinned a break-even **anchor radius**
    ``R* = band_hi - r_foot - target_surface_clearance = 0.38 m``, above which
    ``next_to``'s outer edge lay inside ``near``'s inner edge and the two
    relations disagreed about the same metre.

    With the band measured to the anchor's surface the same arithmetic answers
    a different question: ``(R + band_hi) - minimum_vicinity(R)`` has ``R``
    cancel, so 0.38 m is now the **usable width of the band around an anchor of
    any size**, and no anchor radius can empty the region. The refusal that
    remains is about the *body*: an embodiment whose footprint plus comfort
    clearance exceeds the band's outer edge has nowhere to stand beside
    anything, and that is what the second half asserts.
    """

    envelope = DEFAULT_STAND_OFF_ENVELOPE
    slack = next_to_band_surface_slack_m()
    assert slack == pytest.approx(
        NEXT_TO_BAND_M[1]
        - envelope.footprint_radius_m
        - envelope.target_surface_clearance_m
    )
    assert slack == pytest.approx(0.38)

    # R cancels: every anchor from a pole to a city block is achievable, and by
    # exactly the same margin.
    for radius in (0.0, 0.06, 0.38, 0.45, 0.58, 0.733757, 2.408, 50.0):
        assert next_to_is_achievable(radius)
        assert next_to_band_from_centre(radius)[1] - envelope.minimum_vicinity(
            radius
        ) == pytest.approx(slack)

    # ...and a genuinely unreachable affordance is still refused. Two ways, both
    # of them the body rather than the anchor: a band whose outer edge is inside
    # the body's own comfort envelope, and a body too big for the shipping band.
    assert not next_to_is_achievable(0.733757, band_m=(0.4, 1.0))
    big_body = dataclasses.replace(
        envelope, envelope=dataclasses.replace(envelope.envelope, footprint_radius_m=0.9)
    )
    assert next_to_band_surface_slack_m(envelope=big_body) < 0.0
    for radius in (0.0, 0.06, 0.733757, 2.408):
        assert not next_to_is_achievable(radius, envelope=big_body)


def test_the_one_class_without_next_to_declares_a_semantic_exclusion() -> None:
    """No class may drop ``next_to`` for taste **without saying so in the file**.

    The 2026-08-08 version of this test asserted the converse of the check
    above: a class without the affordance had to have an instance whose radius
    failed the derivation. That converse is no longer available — surface
    anchoring makes every radius achievable — and pretending otherwise would be
    the dishonest option. So the invariant is restated as what is actually
    true: exactly one class is excluded, its exclusion is **declared** in the
    sidecar as a vocabulary choice rather than a measurement, and the file says
    so in words a reader can check.
    """

    truth = json.loads((REPO / "evals/nav_instruct/scene_truth.json").read_text())["derived"]
    semantics = load_scene_semantics(SIDECAR)
    radii: dict[str, list[float]] = {}
    for entity in truth.values():
        if entity["kind"] != "object":
            continue
        radii.setdefault(entity["label"], []).append(float(entity["radius_m"]))

    excluded = sorted(
        label
        for label, values in radii.items()
        if "next_to" not in semantics.get(label).affordances and values
    )
    assert excluded == ["building"], excluded

    # Every class in the scene — including the excluded one — could hold it.
    for label, values in radii.items():
        assert all(next_to_is_achievable(r) for r in values), (label, values)

    # So the exclusion has to be declared, in the file, as what it is.
    source = SIDECAR.read_text(encoding="utf-8")
    building_block = source.split("  building:", 1)[1].split("\n  sidewalk:", 1)[0]
    assert "VOCABULARY choice, not a measurement" in building_block
    assert "landmark_roles: [boundary, obstacle]" in building_block


def test_detector_query_set_covers_every_class_and_alias() -> None:
    semantics = load_scene_semantics(SIDECAR)
    words = set(semantics.detector_query_set())
    for scene_class in semantics.classes:
        assert scene_class.name in words
        assert set(scene_class.aliases) <= words


def test_landmark_roles_are_queryable() -> None:
    semantics = load_scene_semantics(SIDECAR)
    assert {item.name for item in semantics.classes_with_role("traversable")} == {
        "sidewalk",
        "crosswalk",
    }
    assert {item.name for item in semantics.classes_with_role("seating")} == {"bench"}
    assert set(LANDMARK_ROLES) >= {
        role for item in semantics.classes for role in item.landmark_roles
    }


def test_the_shipped_sidecar_loads_through_the_cached_entry_point() -> None:
    assert scene_semantics() is scene_semantics()
    assert scene_semantics().scene.endswith("city_block.xml")


def test_sidecar_carries_no_coordinates() -> None:
    """Geometry stays in the MJCF; this is the anti-drift rule from W0-D."""

    text = SIDECAR.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    data = yaml.safe_load(body)
    assert set(data["classes"]["tree"]) == {
        "kind",
        "aliases",
        "affordances",
        "landmark_roles",
        "size",
        "metadata",
    }
    for scene_class in data["classes"].values():
        assert scene_class["metadata"] == {}
