"""Card C-3 — the cutover: grounding reads the dog's own map.

Four properties this file exists to pin, in the order the pre-registration
(``scrum/20260821/task_13/evidence/C3_PREREGISTRATION.md``) fixed them:

* **A — T0 is byte-identical.** With the source axis absent or set to
  ``oracle``, the mission path returns the caller's own dict objects. Identity,
  not equality: a rebuilt copy would let world coordinates move by a ULP.
* **B — the POI table is a second oracle and is EMPTY off-oracle.** Its four
  ``demo_pois.yaml`` classes reach the semantic path instead of a hardcoded
  coordinate, and the oracle path is unchanged.
* **C — shadow divergence has a taxonomy and two denominators.** Not a feeling.
* **D — the Narnia property survives the loss of the label set.**

The two axes (``perception.tier`` = noise, ``perception.semantic_source`` =
where candidates come from) are orthogonal and a test says so, because
conflating them is the single most likely way a later executor turns the wrong
knob.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pytest

from parcel_robot.backends.base import (
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)
from parcel_robot.detection_adapter.perception_chain import (
    REGISTERED_TIERS,
    PerceptionChain,
    use_perception_chain,
)
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.semantic_map import (
    EVIDENCE_SATURATION_FRAMES,
    evidence_confidence,
    learned_map_candidates,
    semantic_candidates_from_observation,
)
from parcel_robot.perception_abstention import ABSTENTION_REASONS
from parcel_robot.perception_source.selection import (
    REGISTERED_SOURCES,
    SOURCE_LEARNED_MAP,
    SOURCE_ORACLE,
    SOURCE_SHADOW,
    SemanticSourcePolicy,
    SemanticSourceRefused,
    active_semantic_source,
    normalize_source,
    use_learned_map,
    use_semantic_source,
)
from parcel_robot.perception_source.shadow import (
    ADMISSION_FLIP,
    BENIGN_MISS,
    DIVERGENCE_CLASSES,
    HARD_GATE_CLASSES,
    LOCALIZATION_DELTA,
    REFUSAL_FLIP,
    AgreementRow,
    ArmVerdict,
    Divergence,
    SensingEnvelope,
    ShadowLedger,
    ShadowRefused,
    classify,
    envelope_comparability,
)

REPO = Path(__file__).resolve().parents[1]

#: The four ``demo_pois.yaml`` classes. Each one is a directive the POI table
#: grounds to a hardcoded coordinate before perception is ever consulted.
POI_DIRECTIVES = (
    "go to the coffee shop",
    "go to the crosswalk",
    "go to the park",
    "go to the bookstore",
)


@pytest.fixture(autouse=True)
def _restore_process_defaults():
    """Every test leaves the process on the shipping default.

    The three seams here are process-global by design (they mirror
    ``use_pose_provider``). A test that installs one and does not remove it
    would hand the next test a robot reading a different map, which is the kind
    of cross-test leak that makes a suite lie in exactly one direction: towards
    green.
    """

    yield
    use_semantic_source(None)
    use_learned_map(None)
    use_perception_chain(None)


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


class _FakeEntry:
    """The subset of ``MapEntry`` the candidate builder reads."""

    def __init__(
        self,
        entry_id: str,
        label: str,
        x: float,
        y: float,
        *,
        detection_count: int = 20,
        label_support: int = 20,
        evidence_frames: int = 14,
        names: tuple[str, ...] = (),
        visits: int = 3,
        peak_score: float = 0.7,
        hygiene_note: str = "ok",
    ) -> None:
        self.entry_id = entry_id
        self.label = label
        self.surface_x = x
        self.surface_y = y
        self.surface_z = 0.0
        self.detection_count = detection_count
        self.label_support = label_support
        self.evidence_frames = evidence_frames
        self.visits = visits
        self.peak_score = peak_score
        self.hygiene_note = hygiene_note
        self.first_seen_wall_s = 100.0
        self.last_seen_wall_s = 900.0
        self._names = names or (label,)

    def admissible_names(self) -> tuple[str, ...]:
        return self._names


class _FakeMap:
    """Duck-typed ``OnlineSemanticMap`` — the four methods the seam requires."""

    def __init__(self, entries: list[_FakeEntry], *, navigability: float = 1.0) -> None:
        self._entries = entries
        self._navigability = navigability
        self.resolve_calls: list[str] = []

    def active_entries(self):
        return tuple(self._entries)

    def around_me(self, x, y, yaw_rad, *, radius_m=15.0, limit=12):
        rows = []
        for entry in self._entries:
            dx = entry.surface_x - x
            dy = entry.surface_y - y
            distance = math.hypot(dx, dy)
            if distance > radius_m:
                continue
            bearing = math.atan2(dy, dx) - yaw_rad
            bearing = (bearing + math.pi) % (2.0 * math.pi) - math.pi
            rows.append(
                {
                    "entry_id": entry.entry_id,
                    "label": entry.label,
                    "names": list(entry.admissible_names()),
                    "distance_m": distance,
                    "bearing_rad": bearing,
                    "evidence_frames": entry.evidence_frames,
                    "hygiene_note": entry.hygiene_note,
                }
            )
        rows.sort(key=lambda row: (row["distance_m"], row["entry_id"]))
        return tuple(rows[:limit])

    def known_places(self):
        vocabulary = set()
        for entry in self._entries:
            vocabulary.add(entry.label)
            vocabulary.update(entry.admissible_names())
        return tuple(sorted(vocabulary))

    def navigability(self, entry):
        return self._navigability, "robot_traversal"

    def resolve(self, query, **kwargs):
        self.resolve_calls.append(query)


def _observation(*, x: float = 0.0, y: float = 0.0, yaw: float = 0.0) -> SimObservation:
    return SimObservation(
        timestamp=1.0,
        robot=RobotPose(x=x, y=y, yaw=yaw),
        owner=OwnerTrack(x=1.0, y=0.0, visible=True, confidence=0.9),
        semantic_objects=(
            SemanticObjectTrack(
                object_id="lamp_post_1",
                label="lamppost",
                position=(4.0, 2.0, 0.0),
                confidence=0.98,
                source="perception",
                reachable=True,
                metadata={"radius_m": 0.2},
            ),
        ),
        semantic_regions=(
            SemanticRegionTrack(
                region_id="sidewalk",
                label="sidewalk",
                polygon=((-6.0, 2.4), (6.0, 2.4), (6.0, 3.6), (-6.0, 3.6)),
                confidence=0.98,
                source="perception",
                reachable=True,
                metadata={},
            ),
        ),
    )


# --------------------------------------------------------------------------
# D1 — the two axes are orthogonal
# --------------------------------------------------------------------------


def test_tier_and_semantic_source_are_orthogonal_axes() -> None:
    """``tier`` is noise; ``semantic_source`` is provenance. Never the same knob.

    This is the pre-registration's §1 collision, pinned. Frozen ``nav_instruct``
    rows record a ``tier`` field, so a later edit that made ``T1`` mean "read the
    learned map" would silently change what an archived eval row means.
    """

    assert set(REGISTERED_TIERS) == {"T0", "T1"}
    assert set(REGISTERED_SOURCES) == {SOURCE_ORACLE, SOURCE_LEARNED_MAP, SOURCE_SHADOW}
    assert not set(REGISTERED_TIERS) & set(REGISTERED_SOURCES)

    # Installing the T1 NOISE tier must not move the source off oracle.
    use_perception_chain(PerceptionChain.from_tier("T1", seed=7))
    assert active_semantic_source().source == SOURCE_ORACLE
    assert active_semantic_source().poi_grounding_enabled

    # Installing the learned-map SOURCE must not touch the noise tier.
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    from parcel_robot.detection_adapter.perception_chain import active_perception_chain

    assert active_perception_chain().tier.name == "T1"


def test_the_literal_string_T1_is_refused_as_a_source_with_the_reason() -> None:
    """A config that says ``T1`` and means the map must not quietly get the oracle."""

    with pytest.raises(SemanticSourceRefused) as excinfo:
        normalize_source("T1")
    message = str(excinfo.value)
    assert "ambiguous" in message
    assert "learned_map" in message
    assert "perception.tier" in message


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("T0", SOURCE_ORACLE),
        ("oracle", SOURCE_ORACLE),
        ("learned_map", SOURCE_LEARNED_MAP),
        ("T1_MAP", SOURCE_LEARNED_MAP),
        ("T0_shadow_T1", SOURCE_SHADOW),
        ("shadow", SOURCE_SHADOW),
    ],
)
def test_the_cards_spellings_normalise(spelling: str, expected: str) -> None:
    assert normalize_source(spelling) == expected


def test_unknown_source_and_unknown_key_both_refuse() -> None:
    with pytest.raises(SemanticSourceRefused):
        normalize_source("T9")
    with pytest.raises(SemanticSourceRefused):
        SemanticSourcePolicy.from_mapping({"semantic_source_typo": True})
    with pytest.raises(SemanticSourceRefused):
        # A run that logs divergence without naming a source has not chosen one.
        SemanticSourcePolicy.from_mapping({"semantic_source_log_divergence": True})


# --------------------------------------------------------------------------
# A — T0 byte-identity
# --------------------------------------------------------------------------


def test_A1_default_source_returns_the_callers_own_dicts() -> None:
    """Object identity, not equality. A copy could move a coordinate by a ULP."""

    observation = _observation()
    first = semantic_candidates_from_observation(observation)
    second = semantic_candidates_from_observation(observation)
    assert [id(row) for row in first] != [id(row) for row in second], (
        "each call builds fresh oracle rows; identity is asserted through the "
        "chain, below, not across calls"
    )
    # The chain's T0 short-circuit returns the row object it was handed.
    chain = PerceptionChain.from_tier("T0")
    rows = [dict(row) for row in first]
    processed = chain.process(rows, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
    assert [id(row) for row in processed] == [id(row) for row in rows]


def test_A2_explicit_oracle_is_identical_to_the_absent_key() -> None:
    observation = _observation()
    absent = semantic_candidates_from_observation(observation)
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_ORACLE))
    explicit = semantic_candidates_from_observation(observation)
    assert absent == explicit


def test_A_shadow_still_lets_the_oracle_drive() -> None:
    """Shadow READS the learned map; it must never DRIVE from it.

    Confusing these two would let the migration instrument steer the robot,
    which is the one thing shadow mode must not do.
    """

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_SHADOW))
    use_learned_map(_FakeMap([_FakeEntry("e1", "bench", 3.0, 0.0)]))
    observation = _observation()
    rows = semantic_candidates_from_observation(observation)
    labels = {row["label"] for row in rows}
    assert "lamppost" in labels and "sidewalk" in labels
    assert "bench" not in labels
    policy = active_semantic_source()
    assert policy.reads_learned_map and not policy.drives_from_learned_map


def test_A_learned_map_source_never_reads_the_oracle() -> None:
    """Off-oracle the GT read is not discarded — it is never performed."""

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(_FakeMap([_FakeEntry("e1", "bench", 3.0, 0.0)]))
    rows = semantic_candidates_from_observation(_observation())
    assert [row["label"] for row in rows] == ["bench"]
    assert all(row["source"] == "online_map" for row in rows)


def test_A_learned_map_with_nothing_installed_answers_empty_not_oracle() -> None:
    """A silent fallback to ground truth is the failure this card removes."""

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    assert semantic_candidates_from_observation(_observation()) == []


# --------------------------------------------------------------------------
# B — the POI grounder (REVISION 1)
# --------------------------------------------------------------------------


def test_B3_oracle_keeps_the_poi_table_and_its_known_poi_grounding() -> None:
    navigator = DirectiveNavigator.from_config()
    try:
        assert navigator.grounder.enabled
        assert len(navigator.grounder.pois) == 4
        for directive in POI_DIRECTIVES:
            mission = navigator.parse(directive)
            assert mission.metadata["goal_source"] == "known_poi"
            assert mission.goal is not None
    finally:
        navigator.close()


@pytest.mark.parametrize("source", [SOURCE_LEARNED_MAP, SOURCE_SHADOW])
def test_B1_B2_poi_table_is_empty_off_oracle_and_all_four_reach_perception(
    source: str,
) -> None:
    """REVISION §1. Without this, a T1-only mission can pass via a lookup table."""

    use_semantic_source(SemanticSourcePolicy(source=source))
    navigator = DirectiveNavigator.from_config()
    try:
        assert navigator.grounder.pois == []
        assert not navigator.grounder.enabled
        assert navigator.grounder.disabled_reason
        reached = 0
        for directive in POI_DIRECTIVES:
            mission = navigator.parse(directive)
            assert mission.metadata["goal_source"] == "semantic_search"
            assert mission.goal is None
            assert source in mission.metadata["poi_grounding_disabled"]
            reached += 1
        assert reached == len(POI_DIRECTIVES)
    finally:
        navigator.close()


def test_B_a_disabled_grounder_must_carry_its_reason() -> None:
    """"Empty because the operator emptied it" and "empty because T1" differ."""

    with pytest.raises(ValueError, match="must carry its reason"):
        PlaceGrounder.disabled("")
    grounder = PlaceGrounder.disabled("because the card says so")
    with pytest.raises(LookupError, match="POI grounding is disabled"):
        grounder.ground("go to the crosswalk")


def test_B_a_pre_C3_grounder_degrades_on_oracle_and_RAISES_off_oracle() -> None:
    """The BARN v8 bundle regression, pinned.

    A frozen v8 bundle ships a ``PlaceGrounder`` that predates this card while
    taking ``pipeline.py`` as a reviewed replacement source; calling the new
    classmethod unconditionally reddened the whole bundle derivation. The fix
    degrades — but only where the outcome is provably identical. Off-oracle it
    must raise, because a quiet fallback there re-arms the second oracle.
    """

    from parcel_robot.navigation.pipeline import _build_grounder

    class _PreC3Grounder:
        """No ``for_semantic_source``, exactly like the frozen bundle's copy."""

        @staticmethod
        def from_yaml(path):
            return PlaceGrounder.from_yaml(path)

    pois = REPO / "configs" / "navigation" / "cities" / "demo_pois.yaml"
    import parcel_robot.navigation.pipeline as pipeline_module

    original = pipeline_module.PlaceGrounder
    pipeline_module.PlaceGrounder = _PreC3Grounder  # type: ignore[misc]
    try:
        # Oracle / no axis: identical outcome, so the degrade is allowed.
        assert len(_build_grounder(pois, None).pois) == 4
        assert (
            len(_build_grounder(pois, SemanticSourcePolicy(source=SOURCE_ORACLE)).pois) == 4
        )
        # Off-oracle: the disable cannot be honoured, so it must be loud.
        for source in (SOURCE_LEARNED_MAP, SOURCE_SHADOW):
            with pytest.raises(RuntimeError, match="second-oracle still armed"):
                _build_grounder(pois, SemanticSourcePolicy(source=source))
    finally:
        pipeline_module.PlaceGrounder = original  # type: ignore[misc]


def test_B_the_union_is_fail_closed() -> None:
    """Either signal off-oracle empties the table. Asymmetric on purpose."""

    pois = REPO / "configs" / "navigation" / "cities" / "demo_pois.yaml"
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_ORACLE))
    caller_says_map = SemanticSourcePolicy(source=SOURCE_LEARNED_MAP)
    assert PlaceGrounder.for_semantic_source(pois, caller_says_map).pois == []
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_SHADOW))
    caller_says_oracle = SemanticSourcePolicy(source=SOURCE_ORACLE)
    assert PlaceGrounder.for_semantic_source(pois, caller_says_oracle).pois == []


# --------------------------------------------------------------------------
# honest confidence — the 0.98 is gone
# --------------------------------------------------------------------------


def test_evidence_confidence_is_never_a_constant_and_never_reaches_one() -> None:
    """The oracle's stamped 0.98 made every confidence threshold vacuous."""

    seen_once = _FakeEntry("a", "bench", 1.0, 0.0, detection_count=1, label_support=1, evidence_frames=1)
    seen_often = _FakeEntry("b", "bench", 1.0, 0.0, detection_count=40, label_support=40, evidence_frames=40)
    impure = _FakeEntry("c", "bench", 1.0, 0.0, detection_count=40, label_support=8, evidence_frames=40)

    low = evidence_confidence(seen_once)
    high = evidence_confidence(seen_often)
    mixed = evidence_confidence(impure)

    assert 0.0 < low < mixed < high < 1.0, (low, mixed, high)
    assert high < 0.999999, "a finite number of looks has not earned certainty"
    # Monotone in frames, at fixed purity.
    values = [
        evidence_confidence(
            _FakeEntry("x", "bench", 0.0, 0.0, detection_count=n, label_support=n, evidence_frames=n)
        )
        for n in (1, 2, 5, 10, 30)
    ]
    assert values == sorted(values)
    assert len(set(values)) == len(values), "a constant would collapse this to one value"


def test_evidence_confidence_agrees_with_the_abstention_gates_frame_count() -> None:
    """Two modules that mean 'enough observations' must not drift apart."""

    from parcel_robot.perception_abstention import MIN_EVIDENCE_FRAMES

    assert EVIDENCE_SATURATION_FRAMES == float(MIN_EVIDENCE_FRAMES)


def test_learned_map_candidates_carry_evidence_not_a_label_set() -> None:
    entry = _FakeEntry("e1", "bench", 3.0, 0.0, names=("bench", "the green bench"))
    rows = learned_map_candidates(_observation(), learned_map=_FakeMap([entry]))
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "online_map"
    assert row["confidence"] != 0.98
    assert row["confidence"] == pytest.approx(evidence_confidence(entry))
    metadata = row["metadata"]
    assert metadata["semantic_source"] == "learned_map"
    assert metadata["aliases"] == ["bench", "the green bench"]
    assert metadata["evidence_frames"] == entry.evidence_frames
    assert metadata["navigability"] == 1.0
    assert metadata["navigability_source"] == "robot_traversal"


def test_a_place_the_robot_cannot_stand_at_is_not_reachable() -> None:
    entry = _FakeEntry("e1", "bench", 3.0, 0.0)
    rows = learned_map_candidates(
        _observation(), learned_map=_FakeMap([entry], navigability=0.0)
    )
    assert rows[0]["reachable"] is False


def test_out_of_range_places_are_not_candidates() -> None:
    far = _FakeEntry("far", "bench", 400.0, 0.0)
    assert learned_map_candidates(_observation(), learned_map=_FakeMap([far])) == []


def test_use_learned_map_refuses_an_object_that_is_not_a_map() -> None:
    """A wrong object must be refused here, not discovered as an empty list."""

    with pytest.raises(TypeError, match="around_me"):
        use_learned_map(object())


# --------------------------------------------------------------------------
# C — the divergence taxonomy
# --------------------------------------------------------------------------


def test_C_the_taxonomy_is_exactly_four_classes() -> None:
    assert DIVERGENCE_CLASSES == (
        BENIGN_MISS,
        LOCALIZATION_DELTA,
        ADMISSION_FLIP,
        REFUSAL_FLIP,
    )
    assert set(HARD_GATE_CLASSES) == {ADMISSION_FLIP, REFUSAL_FLIP}
    assert len(set(DIVERGENCE_CLASSES)) == 4, "two classes collapsed into one"


def test_C_admission_flip_is_a_hard_gate_in_both_of_its_shapes() -> None:
    refused = ArmVerdict(admitted=False, reason="unseen")
    admitted = ArmVerdict(admitted=True, place_id="p1", label="bench", x=1.0, y=1.0)
    other = ArmVerdict(admitted=True, place_id="p2", label="bench", x=9.0, y=9.0)

    flip = classify(
        query="bench",
        query_class="bench",
        oracle=refused,
        learned=admitted,
        comparable=True,
        frames=("f1",),
    )
    assert flip is not None and flip.divergence_class == ADMISSION_FLIP
    assert flip.is_hard_gate

    swap = classify(
        query="bench",
        query_class="bench",
        oracle=admitted,
        learned=other,
        comparable=True,
        frames=("f1",),
    )
    assert swap is not None and swap.divergence_class == ADMISSION_FLIP
    assert swap.delta_m == pytest.approx(math.hypot(8.0, 8.0))


def test_C_refusal_outside_the_envelope_is_benign_not_a_flip() -> None:
    """Otherwise the envelope is decorative and every distant thing is a defect."""

    oracle = ArmVerdict(admitted=True, place_id="p1", label="bench", x=30.0, y=0.0)
    learned = ArmVerdict(admitted=False, reason="unseen")
    inside = classify(
        query="bench", query_class="bench", oracle=oracle, learned=learned,
        comparable=True, frames=("f1",),
    )
    outside = classify(
        query="bench", query_class="bench", oracle=oracle, learned=learned,
        comparable=False, frames=("f1",),
    )
    assert inside is not None and inside.divergence_class == REFUSAL_FLIP
    assert outside is not None and outside.divergence_class == BENIGN_MISS
    assert not outside.is_hard_gate


def test_C_both_refusing_is_agreement_which_is_the_narnia_case() -> None:
    assert (
        classify(
            query="narnia",
            query_class="absent",
            oracle=ArmVerdict(admitted=False, reason="unknown_place"),
            learned=ArmVerdict(admitted=False, reason="no_label_match"),
            comparable=True,
            frames=("f1",),
        )
        is None
    )


def test_C_localization_delta_respects_the_pg2_tolerance() -> None:
    oracle = ArmVerdict(admitted=True, place_id="p", label="bench", x=0.0, y=0.0)
    near = ArmVerdict(admitted=True, place_id="p", label="bench", x=0.4, y=0.0)
    far = ArmVerdict(admitted=True, place_id="p", label="bench", x=3.0, y=0.0)
    assert classify(
        query="bench", query_class="bench", oracle=oracle, learned=near,
        comparable=True, frames=("f1",), localization_tolerance_m=1.0,
    ) is None
    delta = classify(
        query="bench", query_class="bench", oracle=oracle, learned=far,
        comparable=True, frames=("f1",), localization_tolerance_m=1.0,
    )
    assert delta is not None and delta.divergence_class == LOCALIZATION_DELTA
    assert delta.delta_m == pytest.approx(3.0)


def test_C4_a_divergence_without_its_frames_is_refused() -> None:
    """A divergence that cannot be re-examined is an anecdote, not evidence."""

    with pytest.raises(ShadowRefused, match="frames that produced it"):
        Divergence(
            query="bench",
            query_class="bench",
            divergence_class=ADMISSION_FLIP,
            oracle=ArmVerdict(admitted=False),
            learned=ArmVerdict(admitted=True, place_id="p"),
            comparable=True,
            frames=(),
        )
    with pytest.raises(ShadowRefused):
        Divergence(
            query="bench",
            query_class="bench",
            divergence_class="mystery_class",
            oracle=ArmVerdict(admitted=False),
            learned=ArmVerdict(admitted=True, place_id="p"),
            comparable=True,
            frames=("f1",),
        )


def test_C1_every_agreement_row_carries_both_denominators() -> None:
    """The seeded defect for this is 'agreement reported without denominators'."""

    ledger = ShadowLedger()
    admitted = ArmVerdict(admitted=True, place_id="p1", label="bench", x=1.0, y=1.0)
    ledger.record(
        query="bench", query_class="bench", oracle=admitted, learned=admitted,
        comparable=True, frames=("f1",),
    )
    ledger.record(
        query="bench", query_class="bench",
        oracle=ArmVerdict(admitted=True, place_id="p2", label="bench", x=40.0, y=0.0),
        learned=ArmVerdict(admitted=False, reason="unseen"),
        comparable=False, frames=("f2",),
    )
    rows = ledger.agreement_table()
    assert len(rows) == 1
    row = rows[0].as_dict()
    for key in ("n_total", "n_comparable", "agreement_total", "agreement_comparable"):
        assert key in row, f"{key} missing: a rate without its denominator is not a result"
    assert row["n_total"] == 2
    assert row["n_comparable"] == 1
    assert row["agreement_total"] == pytest.approx(0.5)
    assert row["agreement_comparable"] == pytest.approx(1.0)
    assert row["counts"][BENIGN_MISS] == 1
    summary = ledger.summary()
    assert summary["overall"]["n_total"] == 2
    assert summary["overall"]["n_comparable"] == 1


def test_C_an_empty_class_reports_None_not_a_perfect_score() -> None:
    """n=0 is an absent rate, not a small one. Returning 1.0 would flatter."""

    row = AgreementRow(
        query_class="bench",
        total_comparisons=0,
        comparable_comparisons=0,
        agreements_total=0,
        agreements_comparable=0,
        counts={},
    )
    assert row.rate_total is None
    assert row.rate_comparable is None


def test_C_impossible_counts_are_refused() -> None:
    with pytest.raises(ShadowRefused):
        AgreementRow(
            query_class="bench",
            total_comparisons=1,
            comparable_comparisons=2,
            agreements_total=0,
            agreements_comparable=0,
            counts={},
        )
    with pytest.raises(ShadowRefused):
        AgreementRow(
            query_class="bench",
            total_comparisons=1,
            comparable_comparisons=1,
            agreements_total=2,
            agreements_comparable=0,
            counts={},
        )


def test_C_hard_gate_divergences_are_separable_from_the_soft_ones() -> None:
    ledger = ShadowLedger()
    ledger.record(
        query="bench", query_class="bench",
        oracle=ArmVerdict(admitted=False, reason="unknown"),
        learned=ArmVerdict(admitted=True, place_id="p9", label="bench", x=2.0, y=0.0),
        comparable=True, frames=("f7",),
    )
    ledger.record(
        query="tree", query_class="tree",
        oracle=ArmVerdict(admitted=True, place_id="t1", label="tree", x=50.0, y=0.0),
        learned=ArmVerdict(admitted=False, reason="unseen"),
        comparable=False, frames=("f8",),
    )
    hard = ledger.hard_gate_divergences()
    assert [item.divergence_class for item in hard] == [ADMISSION_FLIP]
    assert ledger.summary()["counts"][BENIGN_MISS] == 1
    assert len(ledger.summary()["hard_gate_divergences"]) == 1


def test_C_an_unestablished_envelope_shrinks_the_comparable_denominator() -> None:
    """Defaulting the other way would inflate agreement for a forgetful harness."""

    oracle = ArmVerdict(admitted=True, place_id="p", label="bench", x=1.0, y=0.0)
    assert not envelope_comparability(
        None, oracle=oracle, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0
    )
    envelope = SensingEnvelope(max_range_m=6.0, half_fov_rad=math.radians(43.5))
    assert envelope_comparability(
        envelope, oracle=oracle, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0
    )
    behind = ArmVerdict(admitted=True, place_id="p", label="bench", x=-1.0, y=0.0)
    assert not envelope_comparability(
        envelope, oracle=behind, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0
    )
    far = ArmVerdict(admitted=True, place_id="p", label="bench", x=20.0, y=0.0)
    assert not envelope_comparability(
        envelope, oracle=far, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0
    )


def test_C_a_shadow_record_without_frames_is_refused() -> None:
    ledger = ShadowLedger()
    with pytest.raises(ShadowRefused, match="frames"):
        ledger.record(
            query="bench", query_class="bench",
            oracle=ArmVerdict(admitted=False),
            learned=ArmVerdict(admitted=False),
            comparable=True, frames=(),
        )


def test_an_admitted_verdict_must_name_a_place() -> None:
    with pytest.raises(ShadowRefused, match="place_id"):
        ArmVerdict(admitted=True)


# --------------------------------------------------------------------------
# D — the Narnia property, without the label set
# --------------------------------------------------------------------------

#: Corpus rows 10–13 (``evals/20260820/voice_corpus_v1/queries.tsv``). These
#: four must refuse under EVERY source. They are the card's single most
#: important assertion: the refusal has to survive the loss of the label set,
#: because after the cutover there is no label set.
CORPUS_REFUSAL_ROWS = (
    ("10", "Go to Narnia."),
    ("11", "Go to my office."),
    ("12", "Take me to the moon."),
    ("13", "Let's go back home."),
)


class _AdmissionHarness:
    """The two runtime methods R20's admission is assembled from, isolated.

    Binding the real methods to a stub avoids constructing a whole runtime while
    still exercising the SHIPPED code path: ``_place_admission`` here is
    ``RobotRuntime._place_admission``, not a re-implementation of it.
    """

    def __init__(self, observation=None) -> None:
        import threading

        from parcel_robot.runtime import RobotRuntime

        self._lock = threading.RLock()
        self._observation = observation
        self._place_admission = RobotRuntime._place_admission.__get__(self)
        self._realtime_scene_vocabulary = (
            RobotRuntime._realtime_scene_vocabulary.__get__(self)
        )
        self._realtime_places = RobotRuntime._realtime_places.__get__(self)
        self._learned_map_vocabulary = RobotRuntime._learned_map_vocabulary.__get__(self)
        self._learned_map_offer_places = (
            RobotRuntime._learned_map_offer_places.__get__(self)
        )


@pytest.mark.parametrize(("row_id", "directive"), CORPUS_REFUSAL_ROWS)
def test_D1_corpus_rows_10_to_13_are_EQUIVALENT_under_both_sources(
    row_id: str, directive: str
) -> None:
    """The PG-3 equivalence tests, extended to T1 — verdict AND reason.

    Equivalence, not "refuses", is the right assertion and the difference is
    load-bearing. Row 13 ("Let's go back home.") is
    ``not_a_navigation_directive`` on BOTH sources: the destination grammar does
    not call it a directive, so R20's gate has no jurisdiction over it and a
    different layer answers. Asserting "refuses" here would have pinned a
    behaviour this gate never had and hidden the property that matters — that
    the cutover moved nothing.
    """

    oracle_harness = _AdmissionHarness(_observation())
    oracle = oracle_harness._place_admission(directive)

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(
        _FakeMap(
            [
                _FakeEntry("e1", "bench", 3.0, 0.0, names=("bench",)),
                _FakeEntry("e2", "lamppost", 5.0, 1.0, names=("lamppost",)),
            ]
        )
    )
    learned = _AdmissionHarness(_observation())._place_admission(directive)

    assert (learned.admitted, learned.reason) == (oracle.admitted, oracle.reason), (
        f"corpus row {row_id} moved across the cutover: "
        f"oracle={oracle.admitted}/{oracle.reason} learned={learned.admitted}/{learned.reason}"
    )
    # And the three rows this gate DOES judge must be refusals under both.
    if oracle.reason != "not_a_navigation_directive":
        assert not learned.admitted, f"corpus row {row_id} admitted under T1"
        assert learned.reason == "unknown_place"


def test_D3_a_known_place_admits_under_the_learned_map() -> None:
    """The other half of D1: refusing everything is not the property either."""

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(_FakeMap([_FakeEntry("e1", "bench", 3.0, 0.0, names=("bench",))]))
    harness = _AdmissionHarness(_observation())
    admission = harness._place_admission("go to the bench")
    assert admission.admitted, admission.reason


def test_D2_the_vocabulary_comes_from_the_map_not_the_scene_sidecar() -> None:
    """The sidecar is not consulted off-oracle — that is what "loss of the label set" means."""

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(
        _FakeMap([_FakeEntry("e1", "kiosk", 3.0, 0.0, names=("kiosk", "the little hut"))])
    )
    harness = _AdmissionHarness(_observation())
    regions, objects = harness._realtime_scene_vocabulary()
    assert regions == ()
    assert set(objects) == {"kiosk", "the little hut"}
    # The oracle observation in the fixture holds a lamppost and a sidewalk, and
    # the scene sidecar declares a much larger class list. Neither may appear.
    assert "lamppost" not in objects
    assert "sidewalk" not in objects
    # A name the map learned but no sidecar ever declared is admissible, which
    # is the growth half of the same property.
    assert harness._place_admission("go to the little hut").admitted


def test_D2_an_empty_learned_map_refuses_rather_than_failing_open() -> None:
    """``admit_navigation_place`` fails OPEN on an empty vocabulary. Not here.

    A sidecar that failed to load must not take navigation down; a map that has
    learned nothing must not admit everything. Same emptiness, opposite correct
    answers, and this is where the two are told apart.
    """

    from parcel_robot.navigation.goals import admit_navigation_place

    # The shipped gate's documented fail-open, unchanged.
    assert admit_navigation_place("go to narnia", ()).admitted

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(_FakeMap([]))
    harness = _AdmissionHarness(_observation())
    for _row_id, directive in CORPUS_REFUSAL_ROWS:
        admission = harness._place_admission(directive)
        if admission.reason == "not_a_navigation_directive":
            # Jurisdiction is unchanged by the conversion: only the fail-open
            # `no_vocabulary` verdict is converted, so a string the destination
            # grammar never called a directive is still not this gate's to judge.
            continue
        assert not admission.admitted
        assert admission.reason == "unknown_place"
    # A place that WOULD be known if the map had learned it is refused too —
    # emptiness refuses, it does not admit.
    assert not harness._place_admission("go to the bench").admitted
    assert harness._place_admission("go to the bench").reason == "unknown_place"


def test_the_oracle_admission_path_is_untouched() -> None:
    harness = _AdmissionHarness(_observation())
    regions, objects = harness._realtime_scene_vocabulary()
    assert "lamppost" in objects
    assert "sidewalk" in regions
    assert not harness._place_admission("Go to Narnia.").admitted
    assert harness._place_admission("go to the lamppost").admitted


# --------------------------------------------------------------------------
# item 4 — scene answerability under the learned map
# --------------------------------------------------------------------------


def test_scene_report_describes_what_the_dog_detected_with_its_uncertainty() -> None:
    from parcel_robot.runtime import (
        SCENE_HONESTY_NOTE,
        SCENE_HONESTY_NOTE_LEARNED_MAP,
        scene_report,
    )

    observation = _observation()
    seen_once = _FakeEntry(
        "e1", "bench", 3.0, 0.0, detection_count=1, label_support=1, evidence_frames=1
    )
    seen_often = _FakeEntry(
        "e2", "tree", 5.0, 1.0, detection_count=40, label_support=40, evidence_frames=40
    )
    report = scene_report(observation, learned_map=_FakeMap([seen_once, seen_often]))

    assert report["semantic_source"] == "learned_map"
    assert report["note"] == SCENE_HONESTY_NOTE_LEARNED_MAP
    assert "no eyes" not in str(report["note"]), "F12: the note becomes false under T1"
    labels = {thing["label"]: thing for thing in report["things"]}
    assert set(labels) == {"bench", "tree"}
    assert labels["bench"]["uncertainty"] == "I've only seen it once"
    assert labels["bench"]["evidence_frames"] == 1
    assert "uncertainty" not in labels["tree"], "a well-observed place needs no hedge"

    oracle = scene_report(observation)
    assert oracle["semantic_source"] == "oracle"
    assert oracle["note"] == SCENE_HONESTY_NOTE
    assert {thing["label"] for thing in oracle["things"]} == {"lamppost", "sidewalk"}


def test_scene_report_keys_match_across_both_arms_and_both_sources() -> None:
    """The docstring promises the same keys; four combinations must honour it."""

    from parcel_robot.runtime import scene_report

    fake = _FakeMap([_FakeEntry("e1", "bench", 3.0, 0.0)])
    keys = [
        set(scene_report(None)),
        set(scene_report(None, learned_map=fake)),
        set(scene_report(_observation())),
        set(scene_report(_observation(), learned_map=fake)),
    ]
    assert keys[0] == keys[1] == keys[2] == keys[3]


def test_the_evidence_hedge_bands_agree_with_the_abstention_gate() -> None:
    from parcel_robot.perception_abstention import MIN_EVIDENCE_FRAMES
    from parcel_robot.runtime import SCENE_EVIDENCE_PHRASES, scene_evidence_phrase

    assert SCENE_EVIDENCE_PHRASES[-1][0] == MIN_EVIDENCE_FRAMES
    assert scene_evidence_phrase(1) == "I've only seen it once"
    assert scene_evidence_phrase(MIN_EVIDENCE_FRAMES) != ""
    assert scene_evidence_phrase(MIN_EVIDENCE_FRAMES + 1) == ""
    assert scene_evidence_phrase(0) == "I've only seen it once"


# --------------------------------------------------------------------------
# G3 — safety does not read the source
# --------------------------------------------------------------------------


def test_G3_the_safety_and_geometry_channels_never_read_the_semantic_source() -> None:
    """Safety rides geometry and dynamic-agent tracks; the tier cannot move it.

    Asserted structurally over the files rather than by running a mission,
    because "no safety module imports the source axis" is a property of the
    tree that a live run can only sample.
    """

    safety_modules = (
        "navigation/reactive_safety.py",
        "navigation/collision.py",
        "navigation/person_keepout.py",
        "navigation/dynamic_layer.py",
        "navigation/dynamic_costs.py",
        "navigation/velocity_shaping.py",
        "navigation/yield_aside.py",
    )
    offenders = []
    for relative in safety_modules:
        path = REPO / "src" / "parcel_robot" / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "perception_source" in text or "semantic_source" in text:
            offenders.append(relative)
    assert offenders == [], (
        f"safety must not read the semantic source: {offenders}"
    )


# --------------------------------------------------------------------------
# E2 — PG-3 is consumed, never forked
# --------------------------------------------------------------------------


#: The modules C-3 wrote or edited. They may CALL the abstention gate; they may
#: not re-declare it.
C3_OWNED_MODULES = (
    "src/parcel_robot/navigation/semantic_map.py",
    "src/parcel_robot/navigation/grounder.py",
    "src/parcel_robot/perception_source/__init__.py",
    "src/parcel_robot/perception_source/selection.py",
    "src/parcel_robot/perception_source/shadow.py",
)

#: Everything a fork would have to copy: the verdict vocabulary and the fitted
#: thresholds. A second spelling of any of these in a C-3 module is the drift
#: this test exists to catch.
_GATE_DECLARATIONS = (
    "def assess_place_query",
    "def ranking_margin",
    "def label_strength_margin",
    "class AbstentionPolicy",
    "class AbstentionVerdict",
    "class DetectorSupport",
    "class PlaceEvidence",
    "MIN_LABEL_PROBABILITY =",
    "MIN_LABEL_FRAMES =",
    "MIN_LABEL_PURITY =",
    "MIN_EVIDENCE_FRAMES =",
    "MIN_GROUND_EVIDENCE_FRACTION =",
    "MIN_RANKING_MARGIN =",
)


def test_E2_the_abstention_gate_is_consumed_never_forked() -> None:
    """REVISION §2's fifth signal is composed on top, never merged in.

    This was a ``git diff`` emptiness pin on ``perception_abstention.py``. Card
    P0-D (``scrum/20260822/task_4``) was chartered to change that module — the
    ranking margin was structurally ``0.0`` on the online map's own background,
    so the fifth gate refused every query no matter what the robot saw — and a
    diff-is-empty ratchet cannot survive a card that is supposed to edit the
    file. It is replaced by the property it was standing in for, which is both
    what E2 meant and stronger than a mtime-free hash: C-3's own modules must
    CALL the shipped gate and must not re-declare its verdicts, its evidence
    types, or its thresholds anywhere of their own.
    """

    offenders: list[str] = []
    for relative in C3_OWNED_MODULES:
        text = (REPO / relative).read_text(encoding="utf-8")
        for declaration in _GATE_DECLARATIONS:
            if declaration in text:
                offenders.append(f"{relative}: {declaration}")
        # The refusal vocabulary must be imported, never re-typed as a literal.
        for reason in sorted(ABSTENTION_REASONS):
            if f'"{reason}"' in text or f"'{reason}'" in text:
                offenders.append(f"{relative}: literal {reason!r}")
    assert offenders == [], (
        "perception_abstention.py is PG-3's, and C-3 consumes it:\n"
        + "\n".join(offenders)
    )

    # And the consumer really does reach the shipped module, so "no fork" is
    # not satisfied by "no gate at all".
    semantic_map = (REPO / "src/parcel_robot/navigation/semantic_map.py").read_text(
        encoding="utf-8"
    )
    assert "from parcel_robot.perception_abstention import" in semantic_map
    assert "assess_place_query" in semantic_map


#: Everything a fork of C-2's map would have to re-declare: the entry/store
#: types, the schema string, and the lifecycle vocabulary. A second spelling of
#: any of these inside a C-3 module is the drift this test exists to catch.
_MAP_DECLARATIONS = (
    "class MapEntry",
    "class MapObservation",
    "class OnlineSemanticMap",
    "class OnlineMapStore",
    "class WriterProvenance",
    "class EmbeddingStamp",
    "MAP_SCHEMA =",
    "PARCEL_ONLINE_MAP_PATH",
)


def test_the_online_map_package_is_consumed_never_forked() -> None:
    """C-2's map is a predecessor deliverable; C-3 reads it, it does not fork it.

    This was a ``git status`` emptiness pin on ``src/parcel_robot/online_map/``
    that asserted every porcelain line began with ``??``. It has stopped
    measuring what it meant, twice over:

    1. The package was UNTRACKED when C-3 wrote this, so "every line is ``??``"
       happened to mean "unmodified". It is tracked now (commit ``71b39a1``),
       so the same assertion means "nobody has touched the map since the last
       commit" — a claim about the working tree of whoever runs the suite, not
       about card C-3.
    2. Card P1-B (``scrum/20260822/task_7``) OWNS ``online_map/`` and was
       chartered to change it: persist the source crop (AU-C2-1), stamp
       ``EvidenceOrigin``, and give the map a product writer. A
       diff-is-empty ratchet cannot survive a later card that is supposed to
       edit the file, and no regeneration can make it true again.

    So it is replaced by the property it stood in for — the same treatment card
    P0-D gave ``test_E2_the_abstention_gate_is_not_modified_by_this_card``, and
    strictly stronger than the emptiness check: C-3's own modules must reach
    the map through its public API and must not re-declare its types, its
    schema or its store path anywhere of their own.
    """

    offenders: list[str] = []
    for relative in C3_OWNED_MODULES:
        text = (REPO / relative).read_text(encoding="utf-8")
        for declaration in _MAP_DECLARATIONS:
            if declaration in text:
                offenders.append(f"{relative}: {declaration}")
    assert offenders == [], (
        "the online map is C-2's, and C-3 consumes it:\n" + "\n".join(offenders)
    )

    # And "no fork" must not be satisfiable by "no map at all": the consumer
    # really does reach the installed map, through the package's public API
    # and through the process seam that says WHICH instance is installed.
    semantic_map = (REPO / "src/parcel_robot/navigation/semantic_map.py").read_text(
        encoding="utf-8"
    )
    # DEC-IG-2: the consumer reaches the map's LEAF modules now that
    # ``online_map/__init__.py`` re-exports nothing. Keyed on the package
    # prefix so it cannot go vacuously green on the next import rewrite.
    assert "from parcel_robot.online_map." in semantic_map
    assert "active_learned_map" in semantic_map
    selection = (REPO / "src/parcel_robot/perception_source/selection.py").read_text(
        encoding="utf-8"
    )
    assert "def use_learned_map" in selection


# --------------------------------------------------------------------------
# cross-process: the default really is the default
# --------------------------------------------------------------------------


def test_a_fresh_interpreter_starts_on_the_oracle() -> None:
    """Import order must not be able to install a source."""

    code = (
        "from parcel_robot.perception_source.selection import active_semantic_source;"
        "import parcel_robot.navigation.semantic_map;"
        "import parcel_robot.navigation.pipeline;"
        "p = active_semantic_source();"
        "print(p.source, p.poi_grounding_enabled)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "oracle True"
