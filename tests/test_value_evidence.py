"""Card VS-3 — value-map evidence policy: match scores, misses, evidence_count.

The card block's gate
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §6, "Card VS-3") is pinned
here, and only this is claimed:

1. paint tuples derive their value from the QUERY-MATCH SCORE through the
   existing embed seam, with the ``string_fallback`` degrade preserved — not
   from the substring test and not from the ``0.15`` / ``0.05`` floors of the
   painter being replaced (record §2.1(2));
2. a scanned cone with zero query evidence paints a MISS, and a miss LOWERS
   the value of the region it covers — demonstrated against a real
   ``SemanticValueMap2D``, not asserted;
3. ``evidence_count`` equals exactly the number of query-relevant evidence
   paints and stays 0 for background-only or miss-only sessions — the number
   card VS-5's empty-map delegation keys on.

Two properties are stated as oracles and each is shown able to FAIL on a
seeded violation.

What these cells do NOT prove: that the eval arms have a camera. In T0 the
observations are the oracle frustum, so the shipped match path here is the
string fallback; the neural path is exercised through an injected synthetic
embedder. Nor do they prove empty-map == baseline: this card makes that claim
provable, VS-5 measures it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import ClassVar

import pytest

from parcel_robot.instructnav.siglip import SIGLIP2_MATCH_THRESHOLD, SigLIP2Matcher
from parcel_robot.navigation import value_evidence
from parcel_robot.navigation.value_evidence import (
    LOOK_CONFIDENCE,
    EvidencePaint,
    ValueEvidenceConfig,
    ValueEvidencePolicy,
    match_observation,
    paint_for_look,
)
from parcel_robot.navigation.value_map import SemanticValueMap2D, ViewCone

#: The floors of the painter this card replaces (pipeline ``_paint_scan_observation``
#: as measured at dd2e857): 0.15 for "cone scanned", 0.05 for "something seen
#: that is not the query". Named here only so their ABSENCE can be asserted.
OLD_PAINTER_SCANNED_FLOOR = 0.15
OLD_PAINTER_OTHER_FLOOR = 0.05


@dataclass(frozen=True)
class _Candidate:
    """A navigator ``SemanticCandidate``-shaped observation."""

    label: str
    confidence: float = 1.0


@dataclass(frozen=True)
class _Detection:
    """A contract ``DetectionMsg``-shaped observation."""

    class_id: str
    score: float = 1.0


class _SyntheticEmbedder:
    """Unit-norm text embeddings with a controlled similarity structure."""

    dim = 2
    _VECTORS: ClassVar[dict[str, tuple[float, float]]] = {
        "lamppost": (1.0, 0.0),
        "streetlight": (0.96, 0.28),
        "tree": (0.2, 0.9797958971132712),
        "bench": (0.0, 1.0),
    }

    def embed_text(self, text: str) -> tuple[float, ...]:
        key = str(text).strip().lower()
        vector = self._VECTORS.get(key)
        if vector is None:
            return (0.0, 1.0)
        norm = math.hypot(*vector)
        return (vector[0] / norm, vector[1] / norm)

    def embed_image(self, image: object) -> tuple[float, ...]:  # pragma: no cover - unused
        raise NotImplementedError


def _neural_matcher() -> SigLIP2Matcher:
    return SigLIP2Matcher(embedder=_SyntheticEmbedder())


def _cone() -> ViewCone:
    return ViewCone(
        origin_world_xy=(0.0, 0.0),
        heading_rad=0.0,
        fov_rad=math.radians(70.0),
        max_range_m=8.0,
        min_range_m=0.4,
    )


def _fresh_map() -> SemanticValueMap2D:
    return SemanticValueMap2D(shape=(12, 12), resolution_m=0.5, origin_global_cell=(0, 0))


# --------------------------------------------------------------------------
# GATE 1 — value comes from the match score, not a substring floor
# --------------------------------------------------------------------------


def test_value_tracks_the_neural_match_score_through_the_embed_seam() -> None:
    matcher = _neural_matcher()
    scores = {
        label: match_observation("lamppost", _Candidate(label), matcher=matcher).match_score
        for label in ("lamppost", "streetlight", "tree", "bench")
    }
    assert scores["lamppost"] == pytest.approx(1.0)
    assert scores["streetlight"] == pytest.approx(0.96)
    assert scores["tree"] == pytest.approx(0.2)
    assert scores["bench"] == pytest.approx(0.0)
    # Strictly ordered by semantic similarity — a substring test cannot do this
    # (none of these labels is a substring of "lamppost").
    assert scores["lamppost"] > scores["streetlight"] > scores["tree"] > scores["bench"]

    for label, score in scores.items():
        paint = paint_for_look("lamppost", [_Candidate(label)], matcher=matcher)
        assert paint.value == pytest.approx(score)
        # The seam, not a substring branch, produced every one of these.
        assert paint.match_source == "siglip2"


def test_evidence_decision_is_the_siglip_operating_point() -> None:
    matcher = _neural_matcher()
    # 0.96 (streetlight/lamppost, a real synonym) clears 0.90; 0.20 does not.
    assert SIGLIP2_MATCH_THRESHOLD == pytest.approx(0.90)
    assert paint_for_look("lamppost", [_Candidate("streetlight")], matcher=matcher).is_evidence
    assert paint_for_look("lamppost", [_Candidate("tree")], matcher=matcher).is_miss
    assert ValueEvidenceConfig().match_threshold == SIGLIP2_MATCH_THRESHOLD


def test_string_fallback_degrade_is_preserved() -> None:
    """No weights loaded: a substring hit scores 1.0, everything else 0.0."""

    matcher = SigLIP2Matcher()
    assert not matcher.available
    hit = paint_for_look("lamppost", [_Candidate("lamppost")], matcher=matcher)
    assert hit.value == 1.0
    assert hit.match_source == "string_fallback"
    assert hit.is_evidence
    miss = paint_for_look("lamppost", [_Candidate("tree")], matcher=matcher)
    assert miss.value == 0.0
    assert miss.match_source == "none"
    assert miss.is_miss


def test_value_is_the_match_score_times_the_observation_confidence() -> None:
    matcher = SigLIP2Matcher()
    for confidence in (0.0, 0.25, 0.5, 1.0):
        paint = paint_for_look(
            "lamppost", [_Candidate("lamppost", confidence=confidence)], matcher=matcher
        )
        assert paint.value == pytest.approx(confidence)
    # Both ingress shapes are accepted.
    detection = paint_for_look("lamppost", [_Detection("lamppost", score=0.4)], matcher=matcher)
    assert detection.value == pytest.approx(0.4)


def test_the_replaced_floors_are_gone() -> None:
    matcher = SigLIP2Matcher()
    empty = paint_for_look("lamppost", [], matcher=matcher)
    assert empty.value == 0.0 != OLD_PAINTER_SCANNED_FLOOR
    assert empty.observations == 0
    other = paint_for_look("lamppost", [_Candidate("bench"), _Candidate("tree")], matcher=matcher)
    assert other.value == 0.0 != OLD_PAINTER_OTHER_FLOOR
    assert other.observations == 2


def test_paint_tuple_shape_is_the_frozen_contract() -> None:
    paint = paint_for_look("lamppost", [_Candidate("lamppost")], matcher=SigLIP2Matcher())
    value, conf, is_evidence = paint.as_tuple()
    assert (value, conf, is_evidence) == (1.0, LOOK_CONFIDENCE, True)
    assert isinstance(paint, EvidencePaint)


def test_config_is_fail_closed() -> None:
    with pytest.raises(ValueError):
        ValueEvidenceConfig(match_threshold=1.5)
    with pytest.raises(ValueError):
        ValueEvidenceConfig(look_confidence=0.0)


# --------------------------------------------------------------------------
# GATE 2 — a miss lowers the value of what it covers
# --------------------------------------------------------------------------


def _painted_cells(value_map: SemanticValueMap2D) -> list[tuple[int, int]]:
    return [
        (x, y)
        for x in range(value_map.shape[1])
        for y in range(value_map.shape[0])
        if value_map.read((x, y))[1] > 0.0
    ]


def test_a_miss_paint_lowers_the_value_of_the_scanned_cone() -> None:
    matcher = SigLIP2Matcher()
    value_map = _fresh_map()
    cone = _cone()

    hit = paint_for_look("lamppost", [_Candidate("lamppost")], matcher=matcher)
    assert value_map.write(cone, hit.value, hit.conf) > 0
    cells = _painted_cells(value_map)
    assert cells, "the cone must cover cells or the demonstration is vacuous"
    before = {cell: value_map.read(cell)[0] for cell in cells}

    miss = paint_for_look("lamppost", [_Candidate("bench")], matcher=matcher)
    assert miss.is_miss
    assert value_map.write(cone, miss.value, miss.conf) > 0
    after = {cell: value_map.read(cell)[0] for cell in cells}

    assert all(after[cell] < before[cell] for cell in cells)
    assert all(after[cell] == pytest.approx(before[cell] / 2.0) for cell in cells)


def test_an_empty_cone_is_a_miss_and_still_paints() -> None:
    matcher = SigLIP2Matcher()
    value_map = _fresh_map()
    cone = _cone()
    value_map.write(cone, 1.0, LOOK_CONFIDENCE)
    cells = _painted_cells(value_map)
    empty = paint_for_look("lamppost", [], matcher=matcher)
    assert empty.is_miss
    assert value_map.write(cone, empty.value, empty.conf) == len(cells)
    assert all(value_map.read(cell)[0] < 1.0 for cell in cells)


def test_repeated_misses_drive_a_region_toward_zero() -> None:
    matcher = SigLIP2Matcher()
    value_map = _fresh_map()
    cone = _cone()
    value_map.write(cone, 1.0, LOOK_CONFIDENCE)
    cells = _painted_cells(value_map)
    previous = value_map.read(cells[0])[0]
    for _ in range(24):
        miss = paint_for_look("lamppost", [_Candidate("tree")], matcher=matcher)
        value_map.write(cone, miss.value, miss.conf)
        current = value_map.read(cells[0])[0]
        assert current < previous
        previous = current
    assert previous < OLD_PAINTER_OTHER_FLOOR


# --------------------------------------------------------------------------
# GATE 3 — the evidence_count contract
# --------------------------------------------------------------------------


def test_evidence_count_counts_exactly_the_query_relevant_paints() -> None:
    policy = ValueEvidencePolicy(matcher=SigLIP2Matcher())
    looks = [
        [_Candidate("bench")],
        [],
        [_Candidate("lamppost")],
        [_Candidate("tree"), _Candidate("bench")],
        [_Candidate("tree"), _Candidate("lamppost")],
        [],
    ]
    paints = [policy.paint("lamppost", look) for look in looks]
    assert [p.is_evidence for p in paints] == [False, False, True, False, True, False]
    assert policy.evidence_count == 2
    assert policy.miss_count == 4
    assert policy.paint_count == 6
    assert policy.evidence_count == sum(1 for p in paints if p.is_evidence)


def test_evidence_count_is_zero_for_background_and_miss_only_sessions() -> None:
    """The empty-map precondition VS-5's delegation keys on."""

    policy = ValueEvidencePolicy(matcher=SigLIP2Matcher())
    for _ in range(25):
        policy.paint("lamppost", [_Candidate("bench"), _Candidate("tree")])
        policy.paint("lamppost", [])
    assert policy.paint_count == 50
    assert policy.miss_count == 50
    assert policy.evidence_count == 0

    # One real sighting is enough to make the map non-empty, and only one.
    policy.paint("lamppost", [_Candidate("lamppost")])
    assert policy.evidence_count == 1


def test_sub_threshold_matches_are_evidence_free_but_still_painted() -> None:
    policy = ValueEvidencePolicy(matcher=_neural_matcher())
    paint = policy.paint("lamppost", [_Candidate("tree")])
    assert paint.value == pytest.approx(0.2)
    assert paint.is_miss
    assert policy.evidence_count == 0


def test_reset_returns_the_policy_to_an_empty_map() -> None:
    policy = ValueEvidencePolicy(matcher=SigLIP2Matcher())
    policy.paint("lamppost", [_Candidate("lamppost")])
    assert policy.evidence_count == 1
    policy.reset()
    assert (policy.evidence_count, policy.miss_count, policy.paint_count) == (0, 0, 0)


# --------------------------------------------------------------------------
# Properties (each shown able to fail on a seeded violation)
# --------------------------------------------------------------------------


def _property_evidence_count_equals_evidence_paints(
    policy: ValueEvidencePolicy, paints: list[EvidencePaint]
) -> None:
    """ORACLE: the ledger counts evidence paints, exactly, and nothing else."""

    expected = sum(1 for paint in paints if paint.is_evidence)
    assert policy.evidence_count == expected
    assert policy.paint_count == len(paints)
    assert policy.miss_count == len(paints) - expected
    if expected == 0:
        assert all(paint.is_miss for paint in paints)


def test_property_evidence_count_matches_the_paints_it_recorded() -> None:
    rng = random.Random(20260811)
    vocabulary = ("lamppost", "streetlight", "tree", "bench")
    for _ in range(60):
        policy = ValueEvidencePolicy(matcher=_neural_matcher())
        paints = []
        for _ in range(rng.randint(0, 12)):
            look = [_Candidate(rng.choice(vocabulary), rng.random()) for _ in range(rng.randint(0, 3))]
            paints.append(policy.paint("lamppost", look))
        _property_evidence_count_equals_evidence_paints(policy, paints)


def test_seeded_violation_kills_the_evidence_count_property() -> None:
    """A ledger that counted every paint would fail the oracle."""

    class _CountsEveryPaint(ValueEvidencePolicy):
        def paint(self, query: str, observations):  # type: ignore[override]
            paint = super().paint(query, observations)
            self._evidence_paints += 1
            return paint

    policy = _CountsEveryPaint(matcher=SigLIP2Matcher())
    paints = [policy.paint("lamppost", [_Candidate("bench")])]
    with pytest.raises(AssertionError):
        _property_evidence_count_equals_evidence_paints(policy, paints)


def _property_miss_never_raises_value(
    before: float, after: float, is_evidence: bool, painted_value: float
) -> None:
    """ORACLE: a paint can only raise a cell's value if it carried evidence."""

    if not is_evidence:
        assert painted_value <= before
        assert after <= before


def test_property_a_miss_can_never_raise_a_cells_value() -> None:
    rng = random.Random(99)
    matcher = _neural_matcher()
    vocabulary = ("lamppost", "streetlight", "tree", "bench")
    for _ in range(60):
        value_map = _fresh_map()
        cone = _cone()
        value_map.write(cone, 1.0, LOOK_CONFIDENCE)
        cells = _painted_cells(value_map)
        cell = cells[rng.randrange(len(cells))]
        before = value_map.read(cell)[0]
        look = [_Candidate(rng.choice(vocabulary), rng.random()) for _ in range(rng.randint(0, 3))]
        paint = paint_for_look("lamppost", look, matcher=matcher)
        value_map.write(cone, paint.value, paint.conf)
        after = value_map.read(cell)[0]
        _property_miss_never_raises_value(before, after, paint.is_evidence, paint.value)


def test_seeded_violation_kills_the_miss_property() -> None:
    """The replaced painter's 0.15 floor is exactly this violation."""

    with pytest.raises(AssertionError):
        _property_miss_never_raises_value(
            before=0.05, after=0.10, is_evidence=False, painted_value=OLD_PAINTER_SCANNED_FLOOR
        )


def test_does_not_prove_is_recorded() -> None:
    assert len(value_evidence.DOES_NOT_PROVE) >= 3
    assert all(isinstance(item, str) and item for item in value_evidence.DOES_NOT_PROVE)
