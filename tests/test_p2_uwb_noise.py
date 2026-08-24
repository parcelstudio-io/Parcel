"""P2 UWB noise model, sim injector, and owner-fusion seam tests."""

from __future__ import annotations

import math
import random
from dataclasses import FrozenInstanceError

import pytest

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.contracts.freshness import expires_from_ttl
from parcel_robot.contracts.v1 import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1, OwnerTrackV1
from parcel_robot.uwb import DOES_NOT_PROVE
from parcel_robot.uwb.fusion import OwnerFusionConfig, OwnerFusionStub
from parcel_robot.uwb.injector import (
    EXTRAS_KEY,
    SimUwbInjector,
    SimUwbPose,
    bearing_range_from_pose,
    uwb_from_extras,
)
from parcel_robot.uwb.model import DEFAULT_UWB_TTL_NS, GroundTruthUwb, UwbNoiseModel
from parcel_robot.uwb.noise import (
    MultipathDropoutSchedule,
    MultipathWindow,
    UwbNoiseConfig,
    schedule_from_windows,
)
from parcel_robot.uwb.sample import UwbSample


def _envelope(
    *,
    evidence_id: str = "e-1",
    received: int = 1_000_000,
    ttl_ns: int = DEFAULT_UWB_TTL_NS,
    source: str = "test",
) -> EvidenceEnvelopeV1:
    return EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence_id,
        source=source,
        source_timestamp_ns=received,
        received_monotonic_ns=received,
        sequence=1,
        frame_id="base_link",
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(
            received_monotonic_ns=received, ttl_ns=ttl_ns
        ),
        calibration_id="test-cal",
        provenance=("test",),
    )


def _detection(
    *,
    class_id: str = "owner",
    bearing: float = 0.0,
    range_m: float = 2.0,
    score: float = 0.9,
    received: int = 1_000_000,
) -> DetectionMsg:
    return DetectionMsg(
        envelope=_envelope(evidence_id="det-1", received=received, source="sim.detection"),
        class_id=class_id,
        embedding=(0.1, 0.2, 0.3),
        bearing_rad=bearing,
        range_m=range_m,
        score=score,
        track_id="trk-1",
    )


def test_multipath_schedule_windows_and_period() -> None:
    schedule = schedule_from_windows([(2, 4)], period_ticks=10, burst_ticks=2)
    assert schedule.is_dropout(2)
    assert schedule.is_dropout(3)
    assert not schedule.is_dropout(4)
    assert schedule.is_dropout(0)
    assert schedule.is_dropout(1)
    assert not schedule.is_dropout(5)
    assert schedule.is_dropout(10)


def test_multipath_bernoulli_requires_draw() -> None:
    schedule = MultipathDropoutSchedule(p_dropout=0.5)
    with pytest.raises(ValueError, match="rng_draw"):
        schedule.is_dropout(0)
    assert schedule.is_dropout(0, rng_draw=0.1)
    assert not schedule.is_dropout(0, rng_draw=0.9)


def test_uwb_noise_config_quality_roll_off() -> None:
    cfg = UwbNoiseConfig()
    assert cfg.expected_quality(1.0) == pytest.approx(cfg.quality_base)
    assert cfg.expected_quality(25.0) == pytest.approx(cfg.quality_far)
    mid = cfg.expected_quality(11.0)
    assert cfg.quality_far < mid < cfg.quality_base


def test_uwb_sample_round_trip_and_freshness() -> None:
    sample = UwbSample(
        envelope=_envelope(),
        fob_id="owner-fob-1",
        bearing_rad=0.25,
        range_m=3.5,
        quality=0.88,
        multipath_suspect=False,
    )
    restored = UwbSample.from_mapping(sample.as_dict())
    assert restored == sample
    sample.require_fresh(1_000_000)
    assert not sample.expired(1_100_000)
    assert sample.expired(1_000_000 + DEFAULT_UWB_TTL_NS)
    payload = sample.bag_payload()
    assert payload["fob_id"] == "owner-fob-1"
    assert "oracle" not in payload
    assert payload["schema_version"] == SCHEMA_VERSION


def test_uwb_sample_rejects_bad_bearing() -> None:
    with pytest.raises(ValueError, match="bearing"):
        UwbSample(
            envelope=_envelope(),
            fob_id="fob",
            bearing_rad=4.0,
            range_m=1.0,
            quality=0.5,
        )


def test_uwb_noise_model_applies_jitter_deterministically() -> None:
    model = UwbNoiseModel(
        UwbNoiseConfig(
            bearing_jitter_std_rad=0.05,
            range_jitter_std_m=0.1,
            quality_jitter_std=0.0,
            multipath=MultipathDropoutSchedule(),
        )
    )
    truth = GroundTruthUwb(fob_id="fob-a", bearing_rad=0.0, range_m=4.0)
    a = model.observe(truth, rng=random.Random(7), received_monotonic_ns=100)
    model.reset()
    b = model.observe(truth, rng=random.Random(7), received_monotonic_ns=100)
    assert a is not None and b is not None
    assert a.bearing_rad == b.bearing_rad
    assert a.range_m == b.range_m
    assert a.envelope.provenance == ("uwb_noise_model_v1",)
    assert abs(a.bearing_rad) > 0.0 or abs(a.range_m - 4.0) > 0.0


def test_uwb_noise_model_range_cutoff() -> None:
    model = UwbNoiseModel(UwbNoiseConfig(range_cutoff_m=5.0))
    truth = GroundTruthUwb(fob_id="fob", bearing_rad=0.1, range_m=6.0)
    assert model.observe(truth, rng=random.Random(1), received_monotonic_ns=1) is None


def test_uwb_noise_model_scheduled_multipath_dropouts() -> None:
    model = UwbNoiseModel(
        UwbNoiseConfig(
            multipath=MultipathDropoutSchedule(
                windows=(MultipathWindow(1, 3),),
            )
        )
    )
    truth = GroundTruthUwb(fob_id="fob", bearing_rad=0.0, range_m=2.0)
    rng = random.Random(0)
    s0 = model.observe(truth, rng=rng, received_monotonic_ns=10)
    s1 = model.observe(truth, rng=rng, received_monotonic_ns=20)
    s2 = model.observe(truth, rng=rng, received_monotonic_ns=30)
    s3 = model.observe(truth, rng=rng, received_monotonic_ns=40)
    assert s0 is not None
    assert s1 is None
    assert s2 is None
    assert s3 is not None


def test_bearing_range_from_pose_body_frame() -> None:
    bearing, range_m = bearing_range_from_pose(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        target_x=3.0,
        target_y=0.0,
    )
    assert range_m == pytest.approx(3.0)
    assert bearing == pytest.approx(0.0)
    bearing_left, _ = bearing_range_from_pose(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        target_x=0.0,
        target_y=2.0,
    )
    assert bearing_left == pytest.approx(math.pi / 2)


def test_sim_injector_attaches_extras_and_round_trips() -> None:
    injector = SimUwbInjector(
        UwbNoiseModel(
            UwbNoiseConfig(
                bearing_jitter_std_rad=0.0,
                range_jitter_std_m=0.0,
                quality_jitter_std=0.0,
            )
        )
    )
    obs = SimObservation(
        timestamp=1.5,
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(owner_id="owner-1", x=2.0, y=0.0, visible=True, confidence=1.0),
        backend="headless",
    )
    extras: dict[str, object] = {"perception_fresh": True}
    sample = injector.observe_and_inject(
        obs, extras, rng=random.Random(3), received_monotonic_ns=1_500_000_000
    )
    assert sample is not None
    assert EXTRAS_KEY in extras
    assert extras[EXTRAS_KEY]["dropout"] is False  # type: ignore[index]
    assert extras[EXTRAS_KEY]["range_m"] == pytest.approx(2.0)  # type: ignore[index]
    restored = uwb_from_extras(extras)
    assert restored is not None
    assert restored.fob_id == "owner-1"
    assert restored.range_m == pytest.approx(2.0)


def test_sim_injector_records_dropout_in_extras() -> None:
    injector = SimUwbInjector(
        UwbNoiseModel(
            UwbNoiseConfig(multipath=MultipathDropoutSchedule(windows=(MultipathWindow(0, 1),)))
        )
    )
    pose = SimUwbPose(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        owner_x=1.0,
        owner_y=0.0,
    )
    extras: dict[str, object] = {}
    sample = injector.sample_from_pose(
        pose, rng=random.Random(0), received_monotonic_ns=100
    )
    injector.inject_extras(extras, sample)
    assert sample is None
    assert extras[EXTRAS_KEY] == {"dropout": True, "schema_version": 1}
    assert uwb_from_extras(extras) is None


def test_uwb_survives_owner_camera_invisible() -> None:
    """UWB is RF — invisible-to-camera owner still yields a sample."""

    injector = SimUwbInjector(
        UwbNoiseModel(
            UwbNoiseConfig(
                bearing_jitter_std_rad=0.0,
                range_jitter_std_m=0.0,
                quality_jitter_std=0.0,
            )
        )
    )
    obs = SimObservation(
        timestamp=0.0,
        robot=RobotPose(),
        owner=OwnerTrack(owner_id="owner-1", x=1.5, y=0.0, visible=False, confidence=0.0),
    )
    sample = injector.sample_from_observation(
        obs, rng=random.Random(1), received_monotonic_ns=50
    )
    assert sample is not None
    assert sample.range_m == pytest.approx(1.5)


def test_fusion_uwb_primary_emits_owner_track_v1() -> None:
    fusion = OwnerFusionStub(OwnerFusionConfig(primary="uwb"))
    uwb = UwbSample(
        envelope=_envelope(received=1_000_000),
        fob_id="owner-fob-1",
        bearing_rad=0.0,
        range_m=2.0,
        quality=0.9,
    )
    vision = _detection(received=1_000_000)
    result = fusion.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=1_000_000,
        uwb=uwb,
        vision=vision,
    )
    assert result.accepted
    assert result.primary_used == "uwb"
    assert isinstance(result.track, OwnerTrackV1)
    assert result.track.state == "confirmed"
    assert result.track.pose.x == pytest.approx(2.0)
    assert result.track.appearance_evidence_refs == (vision.envelope.evidence_id,)
    restored = OwnerTrackV1.from_mapping(result.track.as_dict())
    assert restored.enrolled_owner_id == result.track.enrolled_owner_id


def test_fusion_vision_primary_switch_without_contract_change() -> None:
    uwb_primary = OwnerFusionStub(OwnerFusionConfig(primary="uwb"))
    vision_primary = uwb_primary.with_primary("vision")
    assert vision_primary.config.primary == "vision"

    uwb = UwbSample(
        envelope=_envelope(evidence_id="uwb-1", received=2_000_000),
        fob_id="fob",
        bearing_rad=math.pi / 2,
        range_m=3.0,
        quality=0.8,
    )
    vision = _detection(bearing=0.0, range_m=1.0, received=2_000_000)

    r_uwb = uwb_primary.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=2_000_000,
        uwb=uwb,
        vision=vision,
    )
    r_vis = vision_primary.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=2_000_000,
        uwb=uwb,
        vision=vision,
    )
    assert r_uwb.primary_used == "uwb"
    assert r_vis.primary_used == "vision"
    assert r_uwb.track is not None and r_vis.track is not None
    assert r_uwb.track.pose.y == pytest.approx(3.0)
    assert r_vis.track.pose.x == pytest.approx(1.0)
    assert set(r_uwb.track.as_dict()) == set(r_vis.track.as_dict())


def test_fusion_fail_closed_when_primary_missing() -> None:
    fusion = OwnerFusionStub(OwnerFusionConfig(primary="uwb"))
    result = fusion.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=1_000_000,
        uwb=None,
        vision=_detection(),
    )
    assert not result.accepted
    assert result.reason == "primary_uwb_unavailable"

    vision_fusion = fusion.with_primary("vision")
    result2 = vision_fusion.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=1_000_000,
        uwb=UwbSample(
            envelope=_envelope(),
            fob_id="fob",
            bearing_rad=0.0,
            range_m=1.0,
            quality=0.9,
        ),
        vision=None,
    )
    assert not result2.accepted
    assert result2.reason == "primary_vision_unavailable"


def test_fusion_rejects_stale_and_multipath_suspect_primary() -> None:
    fusion = OwnerFusionStub(OwnerFusionConfig(primary="uwb"))
    stale = UwbSample(
        envelope=_envelope(received=0, ttl_ns=100),
        fob_id="fob",
        bearing_rad=0.0,
        range_m=1.0,
        quality=0.9,
    )
    r1 = fusion.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=1_000,
        uwb=stale,
    )
    assert not r1.accepted

    suspect = UwbSample(
        envelope=_envelope(received=1_000),
        fob_id="fob",
        bearing_rad=0.0,
        range_m=1.0,
        quality=0.9,
        multipath_suspect=True,
    )
    r2 = fusion.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=1_000,
        uwb=suspect,
    )
    assert not r2.accepted


def test_end_to_end_injector_to_fusion() -> None:
    injector = SimUwbInjector(
        UwbNoiseModel(
            UwbNoiseConfig(
                bearing_jitter_std_rad=0.0,
                range_jitter_std_m=0.0,
                quality_jitter_std=0.0,
            )
        )
    )
    obs = SimObservation(
        timestamp=2.0,
        robot=RobotPose(x=1.0, y=1.0, yaw=0.0),
        owner=OwnerTrack(owner_id="owner-1", x=4.0, y=1.0, visible=True, confidence=1.0),
    )
    extras: dict[str, object] = {}
    sample = injector.observe_and_inject(
        obs, extras, rng=random.Random(9), received_monotonic_ns=2_000_000_000
    )
    fusion = OwnerFusionStub(OwnerFusionConfig(primary="uwb"))
    result = fusion.fuse(
        robot_x=1.0,
        robot_y=1.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=2_000_000_000,
        uwb=sample,
        vision=_detection(class_id="owner", bearing=0.0, range_m=3.0, received=2_000_000_000),
    )
    assert result.accepted
    assert result.track is not None
    assert result.track.pose.x == pytest.approx(4.0)
    assert result.track.state == "confirmed"


def test_does_not_prove_honesty_strings() -> None:
    assert DOES_NOT_PROVE
    assert any("HR-2" in line for line in DOES_NOT_PROVE)
    assert any("rt/uwbstate" in line for line in DOES_NOT_PROVE)


def test_frozen_configs() -> None:
    cfg = UwbNoiseConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.range_cutoff_m = 1.0  # type: ignore[misc]
