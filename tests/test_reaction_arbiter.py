"""S5: ReactionArbiter selection engine contracts."""

from __future__ import annotations

import math

from parcel_robot.attention.arbiter import ReactionArbiter, ReactionSpec
from parcel_robot.attention.stimuli import Stimulus, StimulusKind


def _spec(
    name: str,
    *,
    base_rate: float = 0.4,
    tracks: frozenset[str] | None = None,
    cooldown_s: float = 0.0,
    habituation_key: str | None = None,
    gains: dict[str, float] | None = None,
) -> ReactionSpec:
    return ReactionSpec(
        name=name,
        tier=2,
        tracks=tracks or frozenset({"head_gaze"}),
        base_rate=base_rate,
        factor_gains=gains or {"sociability": 1.0},
        cooldown_s=cooldown_s,
        habituation_key=habituation_key,
    )


def test_determinism_under_seed() -> None:
    specs = (_spec("glance"),)
    a = ReactionArbiter(specs, rng_seed=7)
    b = ReactionArbiter(specs, rng_seed=7)
    stimuli = (Stimulus(StimulusKind.SPEECH_ONSET, at_s=0.0, confidence=0.8),)
    factors = {"sociability": 1.0}
    tracks = frozenset({"head_gaze"})
    decisions_a = [
        a.tick(
            now_s=float(i),
            stimuli=stimuli,
            factors=factors,
            available_tracks=tracks,
            vetoed=False,
        )
        for i in range(20)
    ]
    decisions_b = [
        b.tick(
            now_s=float(i),
            stimuli=stimuli,
            factors=factors,
            available_tracks=tracks,
            vetoed=False,
        )
        for i in range(20)
    ]
    assert [d.reaction for d in decisions_a] == [d.reaction for d in decisions_b]
    assert [d.seed for d in decisions_a] == [d.seed for d in decisions_b]


def test_veto_zeros_all_weights() -> None:
    arbiter = ReactionArbiter((_spec("glance"),), rng_seed=1)
    decision = arbiter.tick(
        now_s=0.0,
        stimuli=(),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=True,
    )
    assert decision.reaction is None
    assert decision.weights["glance"] == 0.0
    assert decision.suppressed["glance"] == "t0_veto"


def test_track_contention() -> None:
    arbiter = ReactionArbiter(
        (
            _spec("glance", tracks=frozenset({"head_gaze"})),
            _spec("bounce", tracks=frozenset({"expressive_posture"}), base_rate=0.9),
        ),
        rng_seed=3,
        min_dwell_s=0.0,
    )
    decision = arbiter.tick(
        now_s=0.0,
        stimuli=(Stimulus(StimulusKind.AFFECT, at_s=0.0, confidence=0.9),),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    assert decision.suppressed.get("bounce") == "tracks_unavailable"
    assert "glance" not in decision.suppressed or decision.suppressed["glance"] != "tracks_unavailable"


def test_track_holders_block_other_reactions_until_outcome() -> None:
    """Two specs sharing head_gaze: holder blocks the other until notify_outcome."""

    arbiter = ReactionArbiter(
        (
            _spec("glance", base_rate=1.0, tracks=frozenset({"head_gaze"})),
            _spec("nod", base_rate=1.0, tracks=frozenset({"head_gaze"})),
        ),
        rng_seed=2,
        min_dwell_s=0.0,
        commitment_bonus=1.0,
    )
    first = arbiter.tick(
        now_s=0.0,
        stimuli=(Stimulus(StimulusKind.SPEECH_ONSET, at_s=0.0, confidence=1.0),),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    assert first.reaction is not None
    holder = first.reaction
    other = "nod" if holder == "glance" else "glance"
    second = arbiter.tick(
        now_s=0.1,
        stimuli=(Stimulus(StimulusKind.SPEECH_ONSET, at_s=0.1, confidence=1.0),),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    assert second.suppressed.get(other) == "track_held"
    assert second.reaction in {None, holder}
    arbiter.notify_outcome(holder, success=True, now_s=0.2)
    assert arbiter.snapshot()["track_holders"] == {}
    third = arbiter.tick(
        now_s=0.3,
        stimuli=(Stimulus(StimulusKind.SPEECH_ONSET, at_s=0.3, confidence=1.0),),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    assert "track_held" not in third.suppressed.values()


def test_rate_band_over_10k_draws() -> None:
    arbiter = ReactionArbiter(
        (_spec("glance", base_rate=0.4),),
        rng_seed=11,
        min_dwell_s=0.0,
        commitment_bonus=1.0,
    )
    hits = 0
    n = 10_000
    for i in range(n):
        decision = arbiter.tick(
            now_s=float(i),
            stimuli=(Stimulus(StimulusKind.SPEECH_ONSET, at_s=float(i), confidence=1.0),),
            factors={"sociability": 1.0},
            available_tracks=frozenset({"head_gaze"}),
            vetoed=False,
        )
        if decision.reaction == "glance":
            hits += 1
            arbiter.notify_outcome("glance", success=True, now_s=float(i))
    rate = hits / n
    assert 0.36 <= rate <= 0.44, rate


def test_commitment_bonus_prevents_flicker() -> None:
    specs = (
        _spec("a", base_rate=0.9),
        _spec("b", base_rate=0.9),
    )
    arbiter = ReactionArbiter(specs, rng_seed=5, commitment_bonus=1.25, min_dwell_s=0.6)
    stimuli = (Stimulus(StimulusKind.NAME_HIT, at_s=0.0, confidence=1.0),)
    first = arbiter.tick(
        now_s=0.0,
        stimuli=stimuli,
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    assert first.reaction is not None
    # Within dwell, stick to the same reaction.
    second = arbiter.tick(
        now_s=0.2,
        stimuli=stimuli,
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    assert second.reaction == first.reaction


def test_soft_commitment_after_dwell_prevents_flicker() -> None:
    """min_dwell_s=0: bonus>1 soft-pins vs bonus=1 A↔B flicker.

    Distinct tracks so ``_track_holders`` does not mask the soft-commitment path.
    """

    specs = (
        _spec("a", base_rate=1.0, tracks=frozenset({"head_gaze"})),
        _spec("b", base_rate=1.0, tracks=frozenset({"expressive_posture"})),
    )
    sticky = ReactionArbiter(specs, rng_seed=21, commitment_bonus=2.0, min_dwell_s=0.0)
    flat = ReactionArbiter(specs, rng_seed=21, commitment_bonus=1.0, min_dwell_s=0.0)
    stimuli = (Stimulus(StimulusKind.NAME_HIT, at_s=0.0, confidence=1.0),)
    factors = {"sociability": 1.0}
    tracks = frozenset({"head_gaze", "expressive_posture"})

    def switches(arbiter: ReactionArbiter) -> int:
        prev = None
        count = 0
        for i in range(400):
            decision = arbiter.tick(
                now_s=float(i) * 0.05,
                stimuli=stimuli,
                factors=factors,
                available_tracks=tracks,
                vetoed=False,
            )
            # Do not notify: soft commitment applies while last_reaction holds.
            # Clear track holders so both remain candidates (commitment-only pin).
            arbiter._track_holders.clear()
            if decision.reaction is None:
                continue
            if prev is not None and decision.reaction != prev:
                count += 1
            prev = decision.reaction
        return count

    sticky_n = switches(sticky)
    flat_n = switches(flat)
    assert sticky_n < flat_n, (sticky_n, flat_n)


def test_signed_habituation_tau_honored_not_compounded() -> None:
    """τ≈5 over 5s lands near e^{-1} remaining distance, not tick-compounded."""

    tau = 5.0
    floor = -1.0
    arbiter = ReactionArbiter(
        (_spec("glance", base_rate=0.0, habituation_key="gaze_owner"),),
        rng_seed=9,
        min_dwell_s=0.0,
        signed_tau_s=tau,
        signed_floor=floor,
    )
    def _seed(arb: ReactionArbiter) -> None:
        arb.notify_outcome("glance", success=True, now_s=0.0)
        state = arb._habituation["gaze_owner"]
        state.signed_weight = 0.0
        state.last_fire_s = 0.0
        state.last_decay_s = 0.0
        state.engaged = True

    _seed(arbiter)
    # Single jump of one τ.
    arbiter.tick(
        now_s=tau,
        stimuli=(),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"head_gaze"}),
        vetoed=False,
    )
    single = float(arbiter.snapshot()["habituation"]["gaze_owner"]["signed_weight"])  # type: ignore[index]
    expected = floor + (0.0 - floor) * math.exp(-1.0)
    assert abs(single - expected) < 0.02, (single, expected)

    # Many small ticks over the same horizon must land near the same value.
    arbiter2 = ReactionArbiter(
        (_spec("glance", base_rate=0.0, habituation_key="gaze_owner"),),
        rng_seed=9,
        min_dwell_s=0.0,
        signed_tau_s=tau,
        signed_floor=floor,
    )
    _seed(arbiter2)
    for i in range(1, 51):
        arbiter2.tick(
            now_s=i * (tau / 50.0),
            stimuli=(),
            factors={"sociability": 1.0},
            available_tracks=frozenset({"head_gaze"}),
            vetoed=False,
        )
    multi = float(arbiter2.snapshot()["habituation"]["gaze_owner"]["signed_weight"])  # type: ignore[index]
    assert abs(multi - expected) < 0.02, (multi, expected)
    # Compounding-every-tick would drive much closer to the floor.
    assert multi > floor + 0.2


def test_signed_habituation_goes_negative_then_recovers_via_notify_false() -> None:
    arbiter = ReactionArbiter(
        (_spec("glance", base_rate=1.0, habituation_key="gaze_owner", cooldown_s=0.0),),
        rng_seed=9,
        min_dwell_s=0.0,
        signed_tau_s=5.0,
        signed_floor=-1.0,
    )
    for i in range(6):
        decision = arbiter.tick(
            now_s=float(i),
            stimuli=(Stimulus(StimulusKind.SPEECH_ONSET, at_s=float(i), confidence=1.0),),
            factors={"sociability": 1.0},
            available_tracks=frozenset({"head_gaze"}),
            vetoed=False,
        )
        if decision.reaction:
            arbiter.notify_outcome("glance", success=True, now_s=float(i))
    snap = arbiter.snapshot()
    signed = float(snap["habituation"]["gaze_owner"]["signed_weight"])  # type: ignore[index]
    assert signed < 0.0
    # Frozen API: notify_outcome(success=False) resets signed weight for the key.
    arbiter.notify_outcome("glance", success=False, now_s=10.0)
    reset = float(arbiter.snapshot()["habituation"]["gaze_owner"]["signed_weight"])  # type: ignore[index]
    assert reset == 0.0
    assert arbiter.snapshot()["habituation"]["gaze_owner"]["engaged"] is False  # type: ignore[index]
