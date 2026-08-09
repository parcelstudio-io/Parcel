"""RelationSpec registry: lookup layer, K0 delegation, and the JEPD measurement.

Two things are under test here.

1. **The registry is a lookup layer, not a second geometry.** Every registered
   relation must produce exactly the ``GoalRegion`` the K0 builder in
   ``instructnav.scoring`` produces, and ``goals.py``'s directive grammar must
   parse exactly as it did before its preposition alternations were derived
   from the registry.

2. **The proximity family's JEPD status, measured rather than asserted.**
   "Exactly one of near/next_to/towards at any distance" is the property this
   family would have if the bands partitioned the ray. They do not. These tests
   pin *where* they overlap and *where they leave gaps*, so a band edit that
   changes either is a red build.
"""

from __future__ import annotations

import re

import pytest

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    TOWARDS_BAND_M,
    object_near_envelope_m,
    object_near_goal_region,
    object_next_to_goal_region,
    object_towards_goal_region,
    region_inside_goal_region,
)
from parcel_robot.navigation import goals
from parcel_robot.navigation.relation_registry import (
    PROXIMITY_FAMILY,
    RELATIONS,
    RelationAnchor,
    RelationRegistry,
    RelationSpec,
    proximity_band_overlaps,
    proximity_labels_at,
    resolve_relation_word,
)

_SQUARE = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))


# --- the registry itself ---------------------------------------------------


def test_every_registered_relation_is_reachable_by_name_and_alias() -> None:
    for spec in RELATIONS.specs():
        assert RELATIONS.get(spec.name) is spec
        for alias in spec.aliases:
            assert resolve_relation_word(alias) is spec
    assert resolve_relation_word("teleport to") is None


def test_registration_is_fail_closed_on_duplicate_names_and_stolen_aliases() -> None:
    registry = RelationRegistry()
    spec = RelationSpec(
        name="beyond",
        aliases=("beyond",),
        anchor_kinds=("object",),
        frame_of_reference="relative",
        terminal_behavior="stop",
        summary="past the anchor",
    )
    registry.register(spec)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)
    clash = RelationSpec(
        name="past",
        aliases=("beyond",),
        anchor_kinds=("object",),
        frame_of_reference="relative",
        terminal_behavior="stop",
        summary="clashing alias",
    )
    with pytest.raises(ValueError, match="already resolves to relation"):
        registry.register(clash)


def test_a_new_relation_is_data_not_a_code_path() -> None:
    """The extension seam: register + a builder, nothing else."""

    registry = RelationRegistry()
    registry.register(
        RelationSpec(
            name="inside",
            aliases=("inside",),
            anchor_kinds=("region",),
            frame_of_reference="absolute",
            terminal_behavior="stop",
            summary="inside a polygon",
            goal_region_builder=lambda anchor: region_inside_goal_region(anchor.polygon or ()),
        )
    )
    anchor = RelationAnchor(kind="region", polygon=_SQUARE)
    assert registry.get("inside").holds((2.0, 2.0), anchor)
    assert not registry.get("inside").holds((9.0, 9.0), anchor)


def test_anchor_kinds_are_enforced_rather_than_coerced() -> None:
    owner_only = RELATIONS.get("follow")
    with pytest.raises(ValueError, match="does not accept"):
        owner_only.goal_region(RelationAnchor(kind="object", center=(1.0, 0.0)))
    region_only = RELATIONS.get("inside")
    with pytest.raises(ValueError, match="does not accept"):
        region_only.goal_region(RelationAnchor(kind="object", center=(1.0, 0.0)))


def test_orbit_reports_no_goal_region_instead_of_inventing_one() -> None:
    """A trajectory predicate must not be given a fake disc to agree with."""

    orbit = RELATIONS.get("orbit")
    assert orbit.has_goal_region is False
    with pytest.raises(ValueError, match="trajectory property"):
        orbit.goal_region(RelationAnchor(kind="owner", center=(0.0, 0.0)))


def test_frame_of_reference_policy_is_declared_for_every_relation() -> None:
    # `behind` is the only intrinsic-frame relation, which is exactly why it —
    # and not plain follow — carries the owner_heading_available precondition.
    intrinsic = {spec.name for spec in RELATIONS.specs() if spec.frame_of_reference == "intrinsic"}
    assert intrinsic == {"behind"}


# --- delegation to the K0 authority ----------------------------------------


@pytest.mark.parametrize(
    ("relation", "anchor", "expected"),
    [
        (
            "near",
            RelationAnchor(kind="object", center=(1.0, 2.0), radius_m=0.6, label="bench", entity_id="bench_1"),
            object_near_goal_region((1.0, 2.0), 0.6, label="bench", entity_id="bench_1"),
        ),
        (
            "next_to",
            RelationAnchor(kind="object", center=(1.0, 2.0), radius_m=0.6, entity_id="bench_1"),
            object_next_to_goal_region((1.0, 2.0), 0.6, entity_id="bench_1"),
        ),
        (
            "towards",
            RelationAnchor(kind="object", center=(1.0, 2.0), radius_m=0.6, entity_id="bench_1"),
            object_towards_goal_region((1.0, 2.0), entity_id="bench_1"),
        ),
        (
            "inside",
            RelationAnchor(kind="region", polygon=_SQUARE, entity_id="sidewalk"),
            region_inside_goal_region(_SQUARE, entity_id="sidewalk"),
        ),
    ],
)
def test_registry_goal_region_is_the_k0_builder_output(relation, anchor, expected) -> None:
    assert RELATIONS.get(relation).goal_region(anchor) == expected


def test_the_predicate_is_the_same_call_the_scorer_makes() -> None:
    anchor = RelationAnchor(kind="object", center=(0.0, 0.0), radius_m=0.6, entity_id="bench_1")
    region = object_next_to_goal_region((0.0, 0.0), 0.6, entity_id="bench_1")
    spec = RELATIONS.get("next_to")
    for x in (0.0, 0.3, 0.7, 1.0, 1.4, 1.6, 3.0):
        assert spec.holds((x, 0.0), anchor) is region.contains(x, 0.0)


def test_relation_bands_are_not_copied_from_scoring() -> None:
    assert RELATIONS.get("next_to").nominal_band_m == NEXT_TO_BAND_M
    assert RELATIONS.get("towards").nominal_band_m == TOWARDS_BAND_M


# --- goals.py reads its vocabulary from the registry -----------------------


def test_directive_grammar_alternations_come_from_the_registry() -> None:
    assert goals._PROXIMITY_PREPOSITIONS == RELATIONS.preposition_alternation(("near", "next_to"))
    assert goals._TOWARDS_ALIASES == RELATIONS.alias_alternation(("towards",))
    # The exact literals the file used to carry, so the derivation is proven
    # equivalent rather than merely plausible.
    assert set(re.split(r"\|", goals._PROXIMITY_PREPOSITIONS)) == {
        "at",
        "beside",
        "by",
        "near",
        r"next\s+to",
    }
    assert set(re.split(r"\|", goals._TOWARDS_ALIASES)) == {"toward", "towards"}


@pytest.mark.parametrize(
    ("directive", "query", "relation"),
    [
        ("go to the sidewalk", "sidewalk", "inside"),
        ("walk to the bench", "bench", "near"),
        ("go towards the tree", "tree", "towards"),
        ("walk toward the tree", "tree", "towards"),
        ("sit next to the bench", "bench", "next_to"),
        ("wait by the lamppost", "lamppost", "near"),
        ("stand beside the bench", "bench", "near"),
        ("wait at the crosswalk", "crosswalk", "inside"),
        ("go to the nearest sidewalk", "sidewalk", "inside"),
        ("find the nearest lamppost", "lamppost", "near"),
    ],
)
def test_registry_derived_grammar_parses_exactly_as_before(directive, query, relation) -> None:
    goal = goals.semantic_goal_from_directive(directive)
    assert (goal.query, goal.terminal_relation) == (query, relation)


def test_every_terminal_relation_the_parser_can_emit_is_registered() -> None:
    emitted = {
        goals.semantic_goal_from_directive(text).terminal_relation
        for text in (
            "go to the sidewalk",
            "walk to the bench",
            "go towards the tree",
            "sit next to the bench",
        )
    }
    assert emitted <= set(RELATIONS.names())


# --- JEPD: measured, not assumed -------------------------------------------


def test_the_proximity_family_is_not_pairwise_disjoint_and_the_overlap_is_pinned() -> None:
    """JEPD FAILS for this family, on purpose, and this is exactly how much.

    ``next_to`` is a *social placement* band and ``towards`` is a
    *stopped-short-of* band; a pose 1 m from a lamppost honestly satisfies both,
    and also satisfies ``near`` because a lamppost's whole vicinity band sits
    inside both. Collapsing them to force disjointness would mean lying about
    one of the three. What must not drift silently is the size of the overlap.
    """

    overlaps = proximity_band_overlaps(object_radius_m=0.0, label="lamppost")
    # Source: NEXT_TO_BAND_M=(0.4,1.5), TOWARDS_BAND_M=(0.6,2.5), and the
    # lamppost point-anchor near band (1.12, 1.32) from object_near_envelope_m.
    _, near_lo, near_hi = object_near_envelope_m(0.0, label="lamppost")
    assert overlaps[("next_to", "towards")] == (TOWARDS_BAND_M[0], NEXT_TO_BAND_M[1])
    assert overlaps[("next_to", "near")] == (near_lo, near_hi)
    assert overlaps[("near", "towards")] == (near_lo, near_hi)

    # And the strongest single statement: there is a distance at which ALL
    # THREE hold at once.
    assert proximity_labels_at(1.2, object_radius_m=0.0, label="lamppost") == (
        "next_to",
        "near",
        "towards",
    )


def test_the_proximity_family_is_not_jointly_exhaustive_either() -> None:
    """Distances that satisfy no proximity relation at all, both ends."""

    # Inside every band's floor.
    assert proximity_labels_at(0.2, object_radius_m=0.0, label="lamppost") == ()
    # Past every band's ceiling for a small anchor.
    assert proximity_labels_at(2.6, object_radius_m=0.0, label="lamppost") == ()
    # And a *middle* gap for a large anchor: beyond `towards` (which is
    # centre-anchored and ends at 2.5 m) but not yet inside the building's
    # surface-anchored next_to band (2.74-3.84 m) or its near band (3.46-3.96).
    assert proximity_labels_at(2.6, object_radius_m=2.343075, label="building") == ()
    assert proximity_labels_at(3.0, object_radius_m=2.343075, label="building") == (
        "next_to",
    )
    assert proximity_labels_at(3.5, object_radius_m=2.343075, label="building") == (
        "next_to",
        "near",
    )
    # Past every band, including the far edge of next_to.
    assert proximity_labels_at(4.5, object_radius_m=2.343075, label="building") == ()


def test_next_to_around_a_building_sized_anchor_is_a_band_again() -> None:
    """What surface-anchoring the band did to the largest anchor in the scene.

    Until 2026-08-09 this test asserted the opposite — that ``next_to`` was the
    **empty set** around a 2.34 m footprint, because a 0.4-1.5 m band measured
    to the anchor's CENTRE lies entirely inside a 2.34 m anchor. That was the
    same defect the bench had, one order of magnitude larger, and it is what
    made the sidecar's building exclusion look derived.

    With the band measured to the SURFACE the region is a normal annulus
    2.74-3.84 m from the centre, i.e. 0.4-1.5 m from the wall, and every one of
    those poses clears ``minimum_vicinity``. So the geometric argument for
    excluding ``next_to`` from the ``building`` class **no longer exists**: the
    exclusion that remains is a vocabulary choice, and
    ``configs/scenes/city_block.semantics.yaml`` now says so in those words
    rather than claiming a measurement it does not have.
    """

    radius_m = 2.343075
    region = object_next_to_goal_region((0.0, 0.0), radius_m, entity_id="bldg_1")
    assert region.band_m == pytest.approx((radius_m + 0.4, radius_m + 1.5))
    inside = [
        distance
        for distance in (0.5, 1.0, 2.0, 2.4, 2.8, 3.0, 3.5, 3.8, 4.5)
        if "next_to" in proximity_labels_at(distance, object_radius_m=radius_m, label="building")
    ]
    assert inside == [2.8, 3.0, 3.5, 3.8]
    # Every admissible pose is outside the body's own comfort envelope.
    envelope = DEFAULT_STAND_OFF_ENVELOPE
    assert region.band_m is not None
    assert region.band_m[1] >= envelope.minimum_vicinity(radius_m)


def test_proximity_labels_never_disagree_with_the_relations_own_predicate() -> None:
    anchor = RelationAnchor(kind="object", center=(0.0, 0.0), radius_m=0.6, label="bench")
    for step in range(60):
        distance = step * 0.1
        labels = set(
            proximity_labels_at(distance, object_radius_m=0.6, label="bench")
        )
        for name in PROXIMITY_FAMILY:
            assert (name in labels) is RELATIONS.get(name).holds((distance, 0.0), anchor)
