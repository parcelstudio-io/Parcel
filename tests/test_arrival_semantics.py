"""Card R10: the arrival table, and the exact shape of the hybrid relation.

WHAT THIS FILE PINS
-------------------
1. **The split the bench measured.** Model relation hints were 36/36 on both
   tiers; model FACE answers were wrong 6/6 for the door. So a relation hint has
   a validated path in, and face/etiquette have NO path in at all — not a
   parameter, not a schema field, not an argument the broker forwards.
2. **The table wins conflicts.** A hint that contradicts a positively classified
   place loses, and the disagreement is recorded rather than swallowed.
3. **Unknown means near, never a guess** — and the one refinement that IS
   allowed requires local geometry to back it, not a sentence.
4. **Owner words outrank everything.** "wait BY the lamppost" is ``near`` no
   matter what the table or the model would otherwise say.
"""

from __future__ import annotations

import pytest

from parcel_robot.authority import PERSON_SOCIAL_ZONE_M
from parcel_robot.navigation.arrival_semantics import (
    ARRIVAL_TABLE,
    CLASS_OBJECT,
    CLASS_PERSON,
    CLASS_PORTAL,
    CLASS_REGION,
    CLASS_UNKNOWN,
    FACE_OWNER,
    FACE_TRAVEL,
    PLACE_CLASSES,
    RELATION_HINTS,
    RELATION_INSIDE,
    RELATION_NEAR,
    RELATION_SOCIAL,
    SOURCE_HINT_AGREES,
    SOURCE_HINT_REFINES,
    SOURCE_TABLE,
    arrival_fact,
    arrival_policy,
    classify_place,
    planner_relation,
    resolve_relation,
)
from parcel_robot.navigation.goals import semantic_goal_from_directive
from parcel_robot.realtime.tool_broker import TOOL_NAVIGATE_TO, build_tool_specs


# ============================================================ the table itself
def test_the_table_answers_for_every_class_it_declares() -> None:
    assert set(ARRIVAL_TABLE) == set(PLACE_CLASSES)
    for name, policy in ARRIVAL_TABLE.items():
        assert policy.place_class == name
        assert policy.relation in RELATION_HINTS
        assert policy.rationale, f"{name} must say WHY it reads the way it does"


def test_a_door_stops_short_turns_back_and_carries_the_ask() -> None:
    """The owner's scenario 2, entirely in local policy."""

    policy = arrival_policy(CLASS_PORTAL)
    assert policy.relation == RELATION_NEAR
    assert policy.do_not_cross is True
    assert policy.face == FACE_OWNER
    assert policy.ask_hint, "the ask must travel with the arrival, not be hoped for"


def test_a_region_terminates_inside_and_a_person_gets_the_social_zone() -> None:
    assert arrival_policy(CLASS_REGION).relation == RELATION_INSIDE
    assert arrival_policy(CLASS_REGION).face == FACE_TRAVEL
    person = arrival_policy(CLASS_PERSON)
    assert person.relation == RELATION_SOCIAL
    # Derived from the safety authority, never a second hand-typed copy.
    assert person.standoff_m == PERSON_SOCIAL_ZONE_M


def test_an_unknown_class_gets_near_and_never_a_guess() -> None:
    policy = arrival_policy("something nobody declared")
    assert policy.place_class == CLASS_UNKNOWN
    assert policy.relation == RELATION_NEAR


def test_social_reaches_the_same_arrival_authority_as_near() -> None:
    """``social`` is a stand-off, not a second registered predicate."""

    assert planner_relation(RELATION_SOCIAL) == RELATION_NEAR
    assert planner_relation(RELATION_INSIDE) == RELATION_INSIDE


# ================================================================ classification
@pytest.mark.parametrize(
    ("place", "expected"),
    [
        ("the sidewalk", CLASS_REGION),
        ("nearest crosswalk", CLASS_REGION),
        # The bench's firm-gold inside phrasings that no shipped word list had.
        ("the rug", CLASS_REGION),
        ("the kitchen", CLASS_REGION),
        ("the bed", CLASS_REGION),
        ("the door", CLASS_PORTAL),
        ("the front door", CLASS_PORTAL),
        ("the gate", CLASS_PORTAL),
        ("me", CLASS_PERSON),
        ("the owner", CLASS_PERSON),
        ("narnia", CLASS_UNKNOWN),
    ],
)
def test_places_classify_from_their_head_noun(place: str, expected: str) -> None:
    assert classify_place(place) == expected


def test_the_scene_vocabulary_can_supply_classes_this_module_never_heard_of() -> None:
    assert classify_place("bench", object_labels=("bench",)) == CLASS_OBJECT
    assert classify_place("the tarmac", region_labels=("tarmac",)) == CLASS_REGION


def test_a_compound_noun_is_not_split_into_the_wrong_class() -> None:
    """"street light" is a light, not the street — the head noun decides."""

    assert classify_place("street light", object_labels=("street light",)) == CLASS_OBJECT


# =========================================================== the hybrid relation
def test_no_hint_means_the_table_decides_alone() -> None:
    decision = resolve_relation(CLASS_REGION)
    assert (decision.relation, decision.source) == (RELATION_INSIDE, SOURCE_TABLE)
    assert decision.hint_accepted is False
    assert decision.hint == ""


def test_an_agreeing_hint_is_accepted_and_recorded() -> None:
    decision = resolve_relation(CLASS_REGION, "inside")
    assert decision.relation == RELATION_INSIDE
    assert decision.source == SOURCE_HINT_AGREES
    assert decision.hint_accepted is True


def test_a_conflicting_hint_loses_to_the_table_and_says_why() -> None:
    """THE load-bearing assertion of the hybrid: the table wins conflicts."""

    decision = resolve_relation(CLASS_REGION, "near")
    assert decision.relation == RELATION_INSIDE, "the model must not downgrade a region"
    assert decision.source == SOURCE_TABLE
    assert decision.hint_accepted is False
    assert decision.hint_overridden is True
    assert decision.reason == "relation_hint_conflicts_with_class_table"


def test_a_model_cannot_talk_the_robot_into_standing_in_a_doorway() -> None:
    decision = resolve_relation(CLASS_PORTAL, "inside")
    assert decision.relation == RELATION_NEAR
    assert decision.hint_accepted is False
    assert arrival_policy(CLASS_PORTAL).do_not_cross is True


def test_nonsense_hints_lose_quietly_to_the_table() -> None:
    for junk in ("on top of", "", "   ", "INSIDE-ish", "arrive"):
        decision = resolve_relation(CLASS_OBJECT, junk)
        assert decision.relation == RELATION_NEAR
        assert decision.hint_accepted is False


def test_an_unknown_class_may_be_refined_only_when_the_map_backs_it() -> None:
    """The one place a hint changes behaviour — and its evidence gate."""

    unsupported = resolve_relation(CLASS_UNKNOWN, "inside")
    assert unsupported.relation == RELATION_NEAR
    assert unsupported.reason == "relation_hint_unsupported_by_local_map"

    supported = resolve_relation(CLASS_UNKNOWN, "inside", region_support=True)
    assert supported.relation == RELATION_INSIDE
    assert supported.source == SOURCE_HINT_REFINES
    assert supported.hint_accepted is True


def test_a_person_refinement_needs_a_person_not_a_polygon() -> None:
    assert resolve_relation(CLASS_UNKNOWN, "social", region_support=True).relation == RELATION_NEAR
    assert (
        resolve_relation(CLASS_UNKNOWN, "social", person_support=True).relation == RELATION_SOCIAL
    )


# ================================================== face is NOT model-reachable
#: What this pin is actually about: the three arrival knobs the bench measured
#: the model getting wrong 6/6. They are named here rather than inlined so that
#: widening the schema (as ASK-1 did) cannot quietly widen the ABSENCE too.
ARRIVAL_SEMANTICS_FIELDS = frozenset({"face", "standoff", "stop"})


def test_the_tool_schema_offers_relation_and_nothing_else_about_arrival() -> None:
    """The bench: face=goal for the door 6/6, both tiers. So no face parameter.

    A parameter the model cannot send is a parameter it cannot get wrong. This
    asserts the *absence* deliberately — an added ``face``/``standoff``/``stop``
    field would redden here before it could ever reach a body.

    **Card ASK-1 (scrum/20260822/task_18), 2026-08-22 — the pin was MOVED, not
    routed around.** ``navigate_to`` gained a third property, ``confirm``, and
    this test reddened, which is exactly what it is for. The coordinator's
    ruling was to keep the parameter and move the pin deliberately, and the
    reason is that ``confirm`` is not a thing the model can get wrong in the
    sense this test protects: it is an OPAQUE SINGLE-USE TOKEN, compared against
    a verdict the runtime recompiles at the moment of the call, so an invented
    value, a stale value and a replayed value all fail identically and none of
    them reaches a body. It carries no arrival semantics — no face, no standoff,
    no stopping rule — and those three stay absent and are still asserted BY
    NAME, first, so the original property survives the widening: an added
    ``face`` trips that assertion and not merely the set-equality one.
    ``confirm`` must
    also stay OPTIONAL: ``required`` is still exactly ``["place"]``, which is
    what makes a model that has never seen an ``uncertain_place`` result behave
    byte-identically to before that card.
    """

    spec = next(item for item in build_tool_specs() if item["name"] == TOOL_NAVIGATE_TO)
    properties = spec["parameters"]["properties"]
    # The pin's REAL target first, by name, so that this is the assertion an
    # added arrival knob trips — and so it keeps working if a later card widens
    # the set below again, the way ASK-1 did.
    assert not (ARRIVAL_SEMANTICS_FIELDS & set(properties)), (
        "an arrival-semantics parameter reached the model: "
        f"{sorted(ARRIVAL_SEMANTICS_FIELDS & set(properties))}"
    )
    # ...and the set stays exhaustive, so a FOURTH property cannot arrive
    # unnoticed either.
    assert set(properties) == {"place", "relation", "confirm"}
    assert sorted(properties["relation"]["enum"]) == sorted(RELATION_HINTS)
    assert spec["parameters"]["required"] == ["place"]
    assert "confirm" not in spec["parameters"]["required"]


def test_face_and_etiquette_come_only_from_the_table() -> None:
    for name in PLACE_CLASSES:
        policy = arrival_policy(name)
        # Same row, every time, for the same class — no argument, no context,
        # no model. This is what "local only" means operationally.
        assert policy == arrival_policy(name)


# ======================================================== the goal-parsing seam
def test_a_door_directive_compiles_to_a_near_terminal_that_must_not_be_crossed() -> None:
    goal = semantic_goal_from_directive("go to the door")
    assert goal.terminal_relation == "near"
    assert goal.place_class == CLASS_PORTAL
    assert goal.do_not_cross is True
    assert goal.face == FACE_OWNER
    assert goal.ask_hint


def test_a_region_the_old_word_list_missed_now_ends_inside_it() -> None:
    goal = semantic_goal_from_directive("go to the rug")
    assert (goal.kind, goal.terminal_relation) == ("region", "inside")


def test_the_owners_own_preposition_outranks_the_table_and_the_model() -> None:
    """"wait by the lamppost" is near, and no hint can move it."""

    goal = semantic_goal_from_directive("wait by the lamppost", relation_hint="inside")
    assert goal.terminal_relation == "near"


def test_a_supported_hint_can_upgrade_an_unknown_place_through_the_parser() -> None:
    plain = semantic_goal_from_directive("go to the tarmac")
    assert plain.terminal_relation == "near"
    refined = semantic_goal_from_directive(
        "go to the tarmac", relation_hint="inside", region_support=True
    )
    assert (refined.kind, refined.terminal_relation) == ("region", "inside")
    assert refined.relation_source == SOURCE_HINT_REFINES


def test_the_shipped_region_grammar_is_unchanged_by_any_hint() -> None:
    for hint in (None, "near", "social", "inside"):
        goal = semantic_goal_from_directive("go to the sidewalk", relation_hint=hint)
        assert (goal.query, goal.kind, goal.terminal_relation) == (
            "sidewalk",
            "region",
            "inside",
        )


# ================================================================ arrival facts
def test_the_door_arrival_fact_carries_the_ask_inline() -> None:
    """R11 owns the structured hint; until it lands the text travels inline."""

    fact = arrival_fact(place="the door", policy=arrival_policy(CLASS_PORTAL), owner_name="Jae")
    assert "without going through it" in fact
    assert "turned back to face Jae" in fact
    assert "ask the owner what they would like to do next" in fact


def test_a_region_arrival_says_inside_and_asks_nothing() -> None:
    fact = arrival_fact(place="the sidewalk", policy=arrival_policy(CLASS_REGION))
    assert "standing inside the sidewalk" in fact
    assert "ask" not in fact.lower()
