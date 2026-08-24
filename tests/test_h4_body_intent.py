"""H4 capability proof — the body-intent seam does what its contract claims.

One test module for the whole seam (reduced-testing policy,
``research/README.md``).  It proves the four properties the design stands on
and nothing else:

1.  ``degrade`` never invents motion, over random intents and random manifests.
2.  The composer ALWAYS emits — HOLD included — and never originates a velocity.
3.  A manifest round-trips, and a body's declared capabilities are honoured
    exactly, neither more nor less.
4.  The simulator adapter is byte-identical to what ``_dispatch_active`` and
    ``_step_expression`` already put on the wire.

Experiment code and the measured rows live in
``research/20260823/continuous-body-intent/``; this file is the seam's own
regression, and it runs in well under a second.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from parcel_robot.contracts.body_intent import (
    HOLD,
    BodyCapabilityManifest,
    BodyIntentV1,
    Velocity,
    degrade,
    dropped_axes,
    is_no_stronger_than,
)
from parcel_robot.control.go2_sport_body_adapter import (
    GO2_SPORT_MANIFEST,
    Go2SportBodyAdapter,
    Go2SportNotCommissionedError,
    sport_calls_for,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.motion.body_composer import DEFAULT_LIMITS, BodyComposer
from parcel_robot.motion.expression import ExpressiveOffsets
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.simulation.body_adapter import SIM_BODY_MANIFEST, SimulationBodyAdapter

TICK_S = 0.02


class RecordingBody:
    """Records the calls a real ``SimulatorBackend`` would have received."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def expression(self, joint_offsets: dict[str, float]) -> None:
        self.calls.append(("expression", dict(joint_offsets)))

    def move(self, command: VelocityCommand) -> None:
        self.calls.append(("move", command))

    def stop(self) -> None:
        self.calls.append(("stop", None))


def random_intent(rng: random.Random, seq: int) -> BodyIntentV1:
    hold = rng.random() < 0.4
    return BodyIntentV1(
        stamp_ns=seq * 20_000_000,
        epoch=0,
        seq=seq,
        ttl_ms=150,
        locomotion=HOLD
        if hold
        else Velocity(
            vx=rng.uniform(-0.6, 0.6),
            vy=rng.uniform(-0.3, 0.3),
            vyaw=rng.uniform(-1.0, 1.0),
        ),
        posture=(rng.uniform(-0.02, 0.02), rng.uniform(-0.1, 0.1), 0.0),
        gaze=(rng.uniform(-0.7, 0.7), rng.uniform(-0.2, 0.2)),
        breathing_phase=rng.random(),
        style=rng.choice(("calm", "alert", "playful")),
        source="test",
        priority=rng.choice((0, 30, 100)),
    )


def random_manifest(rng: random.Random, index: int) -> BodyCapabilityManifest:
    return BodyCapabilityManifest(
        name=f"body-{index}",
        locomotion_velocity=rng.random() < 0.8,
        hold_is_command=rng.random() < 0.5,
        posture_offsets=rng.random() < 0.5,
        gaze_yaw=rng.random() < 0.5,
        gaze_pitch=rng.random() < 0.5,
    )


# --------------------------------------------------------------------------
# 1. degrade never invents motion
# --------------------------------------------------------------------------
def test_degrade_never_invents_motion_over_random_bodies() -> None:
    rng = random.Random(20260823)
    for index in range(2_000):
        intent = random_intent(rng, index + 1)
        manifest = random_manifest(rng, index)
        fitted = degrade(intent, manifest)
        assert is_no_stronger_than(fitted, intent), (intent, manifest, fitted)
        # A hold is never resurrected into motion, whatever the manifest says.
        if intent.is_hold:
            assert fitted.is_hold
        # Dropping is total: an unsupported axis is exactly zero, not scaled.
        if not manifest.posture_offsets:
            assert fitted.posture == (0.0, 0.0, 0.0)
        if not manifest.gaze_yaw:
            assert fitted.gaze[0] == 0.0
        if not manifest.gaze_pitch:
            assert fitted.gaze[1] == 0.0
        if not manifest.locomotion_velocity:
            assert fitted.is_hold
        # ...and idempotent: fitting a body twice changes nothing.
        assert degrade(fitted, manifest) == fitted


def test_dropped_axes_names_only_axes_that_carried_something() -> None:
    manifest = BodyCapabilityManifest(name="neckless", posture_offsets=False, gaze_yaw=False)
    quiet = BodyIntentV1(
        stamp_ns=0, epoch=0, seq=1, ttl_ms=100, locomotion=HOLD, posture=(0.0, 0.0, 0.0)
    )
    assert dropped_axes(quiet, manifest) == ()
    busy = BodyIntentV1(
        stamp_ns=0,
        epoch=0,
        seq=2,
        ttl_ms=100,
        locomotion=HOLD,
        posture=(0.01, 0.0, 0.0),
        gaze=(0.3, 0.0),
    )
    assert dropped_axes(busy, manifest) == ("posture", "gaze_yaw")


# --------------------------------------------------------------------------
# 2. the composer always emits, and never originates a velocity
# --------------------------------------------------------------------------
def test_composer_emits_every_tick_including_hold() -> None:
    composer = BodyComposer()
    seen: list[BodyIntentV1] = []
    for tick in range(500):
        seen.append(
            composer.compose(
                now_s=tick * TICK_S,
                finalized_velocity=None,
                offsets=ExpressiveOffsets(body_height_m=0.004 * math.sin(tick / 20.0)),
            )
        )
    assert len(seen) == 500
    assert all(intent.is_hold for intent in seen)
    assert [intent.seq for intent in seen] == list(range(1, 501))
    assert composer.hold_ticks == 500


def test_composer_copies_the_finalized_velocity_and_never_makes_one() -> None:
    composer = BodyComposer()
    rng = random.Random(7)
    for tick in range(200):
        command = VelocityCommand(
            vx=rng.uniform(-0.6, 0.6), vy=rng.uniform(-0.3, 0.3), vyaw=rng.uniform(-1.0, 1.0)
        )
        intent = composer.compose(
            now_s=tick * TICK_S, finalized_velocity=command, offsets=ExpressiveOffsets()
        )
        assert intent.velocity is not None
        assert intent.velocity.as_tuple() == (command.vx, command.vy, command.vyaw)
    # No authorized velocity can only ever mean stand still.
    intent = composer.compose(
        now_s=200 * TICK_S, finalized_velocity=None, offsets=ExpressiveOffsets()
    )
    assert intent.is_hold


def test_emergency_holds_and_zeroes_the_body_in_the_same_tick() -> None:
    composer = BodyComposer()
    for tick in range(100):
        composer.compose(
            now_s=tick * TICK_S,
            finalized_velocity=VelocityCommand(vx=0.5),
            offsets=ExpressiveOffsets(body_height_m=0.01, head_yaw_rad=0.5),
        )
    before = composer.epoch
    stopped = composer.compose(
        now_s=100 * TICK_S,
        finalized_velocity=VelocityCommand(vx=0.5),
        offsets=ExpressiveOffsets(body_height_m=0.01, head_yaw_rad=0.5),
        emergency=True,
    )
    assert stopped.is_hold
    assert stopped.priority == 100
    assert stopped.posture == (0.0, 0.0, 0.0)
    assert stopped.gaze == (0.0, 0.0)
    assert composer.epoch == before + 1


def test_posture_and_gaze_stay_inside_the_declared_jerk_bound() -> None:
    """A step target is the worst case; the emitted third difference is bounded."""

    composer = BodyComposer()
    series: list[float] = []
    for tick in range(200):
        target = 0.6 if tick >= 50 else 0.0
        intent = composer.compose(
            now_s=tick * TICK_S,
            finalized_velocity=None,
            offsets=ExpressiveOffsets(head_yaw_rad=target),
        )
        series.append(intent.gaze[0])
    first = [(series[i + 1] - series[i]) / TICK_S for i in range(len(series) - 1)]
    second = [(first[i + 1] - first[i]) / TICK_S for i in range(len(first) - 1)]
    third = [(second[i + 1] - second[i]) / TICK_S for i in range(len(second) - 1)]
    bound = DEFAULT_LIMITS.jerk_bounds()["gaze_yaw"]
    assert max(abs(value) for value in third) <= bound + 1e-6
    assert max(abs(value) for value in first) <= DEFAULT_LIMITS.gaze_yaw.max_rate + 1e-9
    # And it actually gets there: a limiter that never arrives is not a limiter.
    assert series[-1] == pytest.approx(0.6, abs=1e-6)


# --------------------------------------------------------------------------
# 3. manifests round-trip and are honoured exactly
# --------------------------------------------------------------------------
def test_manifest_round_trip_and_rate_lookup() -> None:
    rebuilt = BodyCapabilityManifest(
        name=SIM_BODY_MANIFEST.name,
        locomotion_velocity=SIM_BODY_MANIFEST.locomotion_velocity,
        hold_is_command=SIM_BODY_MANIFEST.hold_is_command,
        posture_offsets=SIM_BODY_MANIFEST.posture_offsets,
        gaze_yaw=SIM_BODY_MANIFEST.gaze_yaw,
        gaze_pitch=SIM_BODY_MANIFEST.gaze_pitch,
        gestures=SIM_BODY_MANIFEST.gestures,
        max_rates=SIM_BODY_MANIFEST.max_rates,
    )
    assert rebuilt == SIM_BODY_MANIFEST
    assert rebuilt.as_dict() == SIM_BODY_MANIFEST.as_dict()
    assert rebuilt.rate("gaze_yaw") == DEFAULT_LIMITS.gaze_yaw.max_rate
    assert rebuilt.rate("nope-not-an-axis", 1.0) == 1.0
    with pytest.raises(ValueError):
        BodyCapabilityManifest(name="bad", max_rates=(("not_an_axis", 1.0),))


def test_go2_manifest_drops_the_head_because_the_body_has_no_neck() -> None:
    intent = BodyIntentV1(
        stamp_ns=0,
        epoch=0,
        seq=1,
        ttl_ms=100,
        locomotion=Velocity(vx=0.3),
        posture=(0.01, 0.05, 0.0),
        gaze=(0.5, 0.1),
    )
    fitted = degrade(intent, GO2_SPORT_MANIFEST)
    assert fitted.gaze == (0.0, 0.0)
    assert fitted.velocity is not None and fitted.velocity.vx == 0.3
    calls = sport_calls_for(intent)
    assert [call.method for call in calls] == ["Move", "Euler"]
    assert calls[0].args == (0.3, 0.0, 0.0)
    # Euler is (roll, pitch, yaw): body yaw belongs to Move, never to posture.
    assert calls[1].args[2] == 0.0


def test_go2_adapter_refuses_every_method_and_imports_no_vendor_sdk() -> None:
    adapter = Go2SportBodyAdapter()
    intent = BodyIntentV1(stamp_ns=0, epoch=0, seq=1, ttl_ms=100, locomotion=HOLD)
    for call in (
        lambda: adapter.activate(),
        lambda: adapter.apply(intent, now_s=0.0),
        lambda: adapter.hold(),
        lambda: adapter.stop("test"),
        lambda: adapter.emergency_stop(),
        lambda: adapter.close(),
    ):
        with pytest.raises(Go2SportNotCommissionedError):
            call()
    assert adapter.commissioned is False
    source = (
        Path(__file__).resolve().parents[1]
        / "src/parcel_robot/control/go2_sport_body_adapter.py"
    ).read_text()
    for forbidden in ("import unitree", "from unitree", "unitree_sdk2", "SportClient("):
        assert forbidden not in source, forbidden


# --------------------------------------------------------------------------
# 4. the simulator adapter changes nothing about what reaches the wire
# --------------------------------------------------------------------------
def test_sim_adapter_matches_todays_dispatch_rule_byte_for_byte() -> None:
    profile = RobotProfile.go2()
    body = RecordingBody()
    composer = BodyComposer()
    adapter = SimulationBodyAdapter(body, profile)
    commands: list[VelocityCommand | None] = []
    rng = random.Random(3)
    for tick in range(300):
        if tick < 100:
            command: VelocityCommand | None = VelocityCommand(vx=0.4)
        elif tick < 200:
            command = VelocityCommand(vx=round(rng.uniform(0.1, 0.5), 3))
        else:
            command = None
        commands.append(command)
        intent = composer.compose(
            now_s=tick * TICK_S, finalized_velocity=command, offsets=ExpressiveOffsets()
        )
        adapter.apply(intent, now_s=tick * TICK_S)

    # Today's rule, replayed here: send on change or after a 0.2 s refresh, and
    # one stop when the intent lapses.
    expected: list[tuple[str, object]] = []
    last: VelocityCommand | None = None
    last_at: float | None = None
    was_moving = False
    for tick, command in enumerate(commands):
        now = tick * TICK_S
        if command is None:
            if was_moving:
                expected.append(("stop", None))
                was_moving = False
                last, last_at = None, None
            continue
        if command != last or last_at is None or now - last_at >= 0.2:
            expected.append(("move", command))
            last, last_at = command, now
            was_moving = any(abs(v) > 1e-6 for v in (command.vx, command.vy, command.vyaw))
    assert [call for call in body.calls if call[0] != "expression"] == expected


def test_sim_adapter_publishes_the_overlay_only_when_it_changes() -> None:
    profile = RobotProfile.go2()
    body = RecordingBody()
    composer = BodyComposer()
    adapter = SimulationBodyAdapter(body, profile)
    for tick in range(60):
        intent = composer.compose(
            now_s=tick * TICK_S,
            finalized_velocity=None,
            offsets=ExpressiveOffsets(body_height_m=0.004),
        )
        adapter.apply(intent, now_s=tick * TICK_S)
    expression_calls = [call for call in body.calls if call[0] == "expression"]
    # It converges on a constant target, so the overlay must stop being resent.
    assert 0 < len(expression_calls) < 60
    assert adapter.expression_publishes == len(expression_calls)
