"""Card VS-2 — false-positive memory: negative evidence with TTL/decay.

The card block's gate
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §6, "Card VS-2") is pinned
here, and only this is claimed:

* ``record_refutation((class, world-cell))`` makes ``suppressed()`` true
  within the TTL and false after the decay, with the TTL and the cell pitch
  DERIVED (``MultiViewConfig.rejected_memory_views`` /
  ``scoring.FALSE_POSITIVE_CELL_M``), not restated;
* the measured commit-then-refute-then-re-encounter sequence — a
  view-consistent phantom that passes ``MultiViewConfirm``'s 3-of-5 window
  (record §2.1(3): the V-B commit landed on view 2 with zero independent
  evidence), is then refuted by card VS-1's verify-on-approach, and is
  re-encountered — is suppressed on the second encounter;
* ``MultiViewConfirm``'s own window-failure memory is a distinct mechanism and
  is behaviourally untouched (``tests/test_vb_multiview_metric.py`` stays
  byte-unchanged and green at 10 passed; this file adds a behavioural
  cross-check, it does not edit that file).

Two properties are stated as oracles and each is shown able to FAIL on a
seeded violation.

What these cells do NOT prove: that a real camera produces the refutation.
In the T0 eval arms persistence is the oracle frustum, which never
hallucinates, so the phantom traces here are injected (record §2.4).
"""

from __future__ import annotations

import math
import random

import pytest

from parcel_robot.contracts.freshness import expires_from_ttl
from parcel_robot.contracts.v1 import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1
from parcel_robot.detection_adapter import false_positive_memory
from parcel_robot.detection_adapter.false_positive_memory import (
    DEFAULT_TTL_VIEWS,
    FalsePositiveMemoryConfig,
    NegativeEvidenceMemory,
)
from parcel_robot.detection_adapter.multi_view_confirm import MultiViewConfig, MultiViewConfirm
from parcel_robot.instructnav.scoring import (
    FALSE_POSITIVE_CELL_M,
    ApproachVerifyState,
    FalsePositiveMemory,
)
from parcel_robot.navigation.lock_on_verify import (
    ApproachView,
    GroundedReference,
    LockOnVerifySession,
    ReferenceKind,
)

PHANTOM_LABEL = "lamppost"
PHANTOM_XY = (10.0, 0.0)


def _detection(view: int, *, score: float = 0.5) -> DetectionMsg:
    timestamp = 1_000_000 + view
    envelope = EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=f"phantom-{view}",
        source="test.pixel",
        source_timestamp_ns=timestamp,
        received_monotonic_ns=timestamp,
        sequence=view,
        frame_id="base_link",
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(received_monotonic_ns=timestamp, ttl_ns=1_000_000),
        calibration_id="test-cal",
        provenance=("test",),
    )
    return DetectionMsg(
        envelope=envelope,
        class_id=PHANTOM_LABEL,
        embedding=(0.1, 0.2),
        bearing_rad=0.0,
        range_m=6.0,
        score=score,
        track_id="phantom-1",
    )


# --------------------------------------------------------------------------
# Derived policy
# --------------------------------------------------------------------------


def test_policy_is_derived_from_the_in_tree_authorities() -> None:
    config = FalsePositiveMemoryConfig()
    assert config.cell_m == FALSE_POSITIVE_CELL_M
    assert config.ttl_views == MultiViewConfig().rejected_memory_views
    assert DEFAULT_TTL_VIEWS == MultiViewConfig().rejected_memory_views
    assert config.max_entries == MultiViewConfig().max_hypotheses


def test_keying_is_the_scorers_own_false_positive_grid() -> None:
    memory = NegativeEvidenceMemory()
    authority = FalsePositiveMemory(cell_m=FALSE_POSITIVE_CELL_M)
    for x, y, label in ((10.0, 0.0, "Lamppost"), (-3.4, 7.9, "tree_2"), (0.0, 0.0, "SIDE walk")):
        assert memory.key(label, (x, y)) == authority.key(x, y, label)


def test_config_is_fail_closed() -> None:
    with pytest.raises(ValueError):
        FalsePositiveMemoryConfig(cell_m=0.0)
    with pytest.raises(ValueError):
        FalsePositiveMemoryConfig(ttl_views=0)
    with pytest.raises(ValueError):
        FalsePositiveMemoryConfig(max_entries=0)
    with pytest.raises(ValueError):
        NegativeEvidenceMemory().suppressed("x", (0.0, 0.0), view_index=-1)


# --------------------------------------------------------------------------
# GATE — suppressed within TTL, released after decay
# --------------------------------------------------------------------------


def test_refutation_suppresses_within_ttl_and_releases_after_decay() -> None:
    memory = NegativeEvidenceMemory()
    assert not memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=0)

    memory.record_refutation(PHANTOM_LABEL, PHANTOM_XY, view_index=0, reason="refuted_on_approach")
    assert memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=0)
    assert memory.strength(PHANTOM_LABEL, PHANTOM_XY, view_index=0) == 1.0

    for age in range(1, DEFAULT_TTL_VIEWS):
        assert memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=age)

    assert not memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=DEFAULT_TTL_VIEWS)
    assert memory.strength(PHANTOM_LABEL, PHANTOM_XY, view_index=DEFAULT_TTL_VIEWS) == 0.0


def test_strength_decays_linearly_and_monotonically() -> None:
    memory = NegativeEvidenceMemory()
    memory.record_refutation(PHANTOM_LABEL, PHANTOM_XY, view_index=0)
    previous = math.inf
    for age in range(DEFAULT_TTL_VIEWS + 5):
        value = memory.strength(PHANTOM_LABEL, PHANTOM_XY, view_index=age)
        assert value <= previous
        expected = max(0.0, 1.0 - age / DEFAULT_TTL_VIEWS)
        assert value == pytest.approx(expected)
        previous = value


def test_repeat_refutations_reinforce_the_horizon() -> None:
    memory = NegativeEvidenceMemory()
    entry = memory.record_refutation(PHANTOM_LABEL, PHANTOM_XY, view_index=0)
    assert memory.horizon_views(entry) == DEFAULT_TTL_VIEWS
    entry = memory.record_refutation(PHANTOM_LABEL, PHANTOM_XY, view_index=0, reason="again")
    assert entry.refutations == 2
    assert memory.horizon_views(entry) == 2 * DEFAULT_TTL_VIEWS
    # The single-refutation TTL has passed; the reinforced entry still holds.
    assert memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=DEFAULT_TTL_VIEWS)
    assert not memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=2 * DEFAULT_TTL_VIEWS)


def test_suppression_survives_a_fresh_id_and_a_cell_boundary() -> None:
    """Keyed by place and class — the two things a detector cannot re-roll."""

    memory = NegativeEvidenceMemory()
    memory.record_refutation(PHANTOM_LABEL, PHANTOM_XY, view_index=0)
    # 20 cm across the cell boundary is the same rejection (scorer's own rule).
    assert memory.suppressed(PHANTOM_LABEL, (PHANTOM_XY[0] + 0.2, PHANTOM_XY[1]), view_index=1)
    assert memory.suppressed(PHANTOM_LABEL, (PHANTOM_XY[0] - 0.9, PHANTOM_XY[1] + 0.9), view_index=1)
    # A different class at the same place is NOT suppressed.
    assert not memory.suppressed("bench", PHANTOM_XY, view_index=1)
    # A place well outside the 3x3 neighbourhood is NOT suppressed.
    assert not memory.suppressed(PHANTOM_LABEL, (PHANTOM_XY[0] + 25.0, 0.0), view_index=1)


def test_consult_reports_strength_count_and_reason() -> None:
    memory = NegativeEvidenceMemory()
    empty = memory.consult(PHANTOM_LABEL, PHANTOM_XY, view_index=0)
    assert not empty.suppressed
    assert empty.reason == "no_negative_evidence"
    assert empty.entry is None

    memory.record_refutation(PHANTOM_LABEL, PHANTOM_XY, view_index=0, reason="covariance")
    hit = memory.consult(PHANTOM_LABEL, PHANTOM_XY, view_index=2)
    assert hit.suppressed
    assert hit.refutations == 1
    assert hit.reason == "covariance"
    assert hit.entry is not None and hit.entry.world_xy == PHANTOM_XY


def test_memory_is_mission_scoped_and_bounded() -> None:
    memory = NegativeEvidenceMemory(FalsePositiveMemoryConfig(max_entries=4))
    for index in range(12):
        memory.record_refutation(PHANTOM_LABEL, (index * 5.0, 0.0), view_index=index)
    assert len(memory) <= 4
    memory.reset()
    assert len(memory) == 0
    assert not memory.suppressed(PHANTOM_LABEL, (0.0, 0.0), view_index=12)


def test_prune_drops_only_decayed_entries() -> None:
    memory = NegativeEvidenceMemory()
    memory.record_refutation(PHANTOM_LABEL, (0.0, 0.0), view_index=0)
    memory.record_refutation(PHANTOM_LABEL, (50.0, 0.0), view_index=DEFAULT_TTL_VIEWS)
    assert memory.prune(view_index=DEFAULT_TTL_VIEWS) == 1
    assert len(memory) == 1
    assert memory.entries(view_index=DEFAULT_TTL_VIEWS)[0].world_xy == (50.0, 0.0)


# --------------------------------------------------------------------------
# GATE — the measured commit → refute → re-encounter sequence
# --------------------------------------------------------------------------


def test_commit_then_refute_then_re_encounter_is_suppressed() -> None:
    """V-B phantom passes M-of-N, VS-1 refutes it, VS-2 remembers the place."""

    # 1. The view-consistent phantom passes MultiViewConfirm's 3-of-5 window.
    confirmer = MultiViewConfirm()
    committed_on = None
    for view in range(1, 6):
        confirmed, credibility, _ = confirmer.update(_detection(view))
        if confirmed and committed_on is None:
            committed_on = view
    assert committed_on is not None, "the phantom must pass M-of-N (record §2.1(3))"
    assert credibility >= MultiViewConfig().credibility_threshold

    # 2. Verify-on-approach refutes it: it never shrinks as the body closes.
    reference = GroundedReference(
        landmark_id="lamppost_1",
        kind=ReferenceKind.OBJECT,
        label=PHANTOM_LABEL,
        center=PHANTOM_XY,
    )
    session = LockOnVerifySession(reference)
    verdict = None
    for step in range(24):
        verdict = session.observe(
            ApproachView(
                robot_xy=(PHANTOM_XY[0] - 8.0 + 0.4 * step, 0.0),
                fused_xy=PHANTOM_XY,
                covariance=((0.04, 0.0), (0.0, 0.04)),
            )
        )
        if verdict.refuted:
            break
    assert session.state is ApproachVerifyState.REJECTED
    evidence = session.negative_evidence()
    assert evidence is not None

    # 3. The refutation is written as negative evidence.
    memory = NegativeEvidenceMemory()
    assert not memory.suppressed(evidence.label, evidence.world_xy, view_index=0)
    memory.record_refutation(
        evidence.label, evidence.world_xy, view_index=0, reason=evidence.reason
    )

    # 4. Second encounter of the SAME class at the SAME place, fresh track id:
    #    suppressed, and the reason names the refutation.
    consult = memory.consult(PHANTOM_LABEL, (PHANTOM_XY[0] + 0.3, PHANTOM_XY[1]), view_index=5)
    assert consult.suppressed
    assert consult.reason == evidence.reason


def test_multi_view_confirm_window_memory_is_a_distinct_untouched_mechanism() -> None:
    """Flicker vs persistence: the two memories answer different questions."""

    # Flicker: 1 hit then misses ⇒ MultiViewConfirm remembers the REJECTION.
    confirmer = MultiViewConfirm()
    confirmer.update(_detection(1, score=0.9))
    for view in range(5):
        confirmer.update(None)
    assert confirmer.rejected_ids == ("phantom-1",)

    # The same trace writes NOTHING to the negative-evidence memory: no
    # verify-on-approach refutation happened.
    memory = NegativeEvidenceMemory()
    assert len(memory) == 0
    assert not memory.suppressed(PHANTOM_LABEL, PHANTOM_XY, view_index=0)

    # And a live negative-evidence memory does not perturb the confirmer.
    control = MultiViewConfirm()
    control.update(_detection(1, score=0.9))
    for view in range(5):
        control.update(None)
    assert control.rejected_ids == confirmer.rejected_ids


# --------------------------------------------------------------------------
# Properties (each shown able to fail on a seeded violation)
# --------------------------------------------------------------------------


def _property_never_resurrects(samples: list[tuple[int, float]]) -> None:
    """ORACLE: strength is non-increasing in age and never returns from zero."""

    seen_zero = False
    previous = math.inf
    for _age, value in samples:
        assert value <= previous + 0.0
        if seen_zero:
            assert value == 0.0
        if value == 0.0:
            seen_zero = True
        previous = value


def test_property_suppression_never_resurrects() -> None:
    rng = random.Random(20260811)
    for _ in range(50):
        memory = NegativeEvidenceMemory()
        label = rng.choice(("lamppost", "tree", "bench"))
        point = (rng.uniform(-40.0, 40.0), rng.uniform(-40.0, 40.0))
        written = rng.randint(0, 5)
        memory.record_refutation(label, point, view_index=written)
        samples = [
            (age, memory.strength(label, point, view_index=age))
            for age in range(written, written + 2 * DEFAULT_TTL_VIEWS)
        ]
        _property_never_resurrects(samples)


def test_seeded_violation_kills_the_no_resurrection_property() -> None:
    resurrecting = [(0, 1.0), (1, 0.5), (2, 0.0), (3, 0.9)]
    with pytest.raises(AssertionError):
        _property_never_resurrects(resurrecting)


def _property_key_agrees_with_the_authority(
    memory: NegativeEvidenceMemory, label: str, point: tuple[float, float]
) -> None:
    """ORACLE: this memory's cell key IS the scorer's cell key."""

    authority = FalsePositiveMemory(cell_m=memory.config.cell_m)
    assert memory.key(label, point) == authority.key(point[0], point[1], label)


def test_property_keys_agree_with_the_scoring_authority() -> None:
    rng = random.Random(4242)
    memory = NegativeEvidenceMemory()
    for _ in range(300):
        label = rng.choice(("Lamppost", "tree_2", "side walk", "BENCH"))
        point = (rng.uniform(-100.0, 100.0), rng.uniform(-100.0, 100.0))
        _property_key_agrees_with_the_authority(memory, label, point)


def test_seeded_violation_kills_the_key_agreement_property() -> None:
    """A memory on a different pitch would key a different place."""

    forked = NegativeEvidenceMemory(FalsePositiveMemoryConfig(cell_m=FALSE_POSITIVE_CELL_M / 4.0))
    authority = FalsePositiveMemory(cell_m=FALSE_POSITIVE_CELL_M)
    point = (10.0, 0.0)
    assert forked.key("lamppost", point) != authority.key(point[0], point[1], "lamppost")
    with pytest.raises(AssertionError):
        # Same oracle, but asserted against the SHIPPED pitch authority.
        assert forked.key("lamppost", point) == authority.key(point[0], point[1], "lamppost")


def test_does_not_prove_is_recorded() -> None:
    assert len(false_positive_memory.DOES_NOT_PROVE) >= 3
    assert all(isinstance(item, str) and item for item in false_positive_memory.DOES_NOT_PROVE)
