"""Owner fusion seam stub — vision vs UWB primary without contract change.

``OwnerTrackV1`` stays channel-agnostic (K1 freeze). This module selects which
sensor *feeds pose* into that DTO. Appearance / identity refs still come from
vision when available. Invert ``primary`` after P5 UWB characterization (HR-2)
without touching consumers of ``OwnerTrackV1``.

Documented switch surface
-------------------------
- ``OwnerChannelPrimary`` ∈ {``"vision"``, ``"uwb"``}
- ``OwnerFusionConfig.primary`` — which channel must be fresh to emit
  ``confirmed`` / ``ambiguous``; the other channel is optional corroboration.
- Output is always ``OwnerTrackV1`` (or ``None`` when fail-closed lost).

No Kalman / IMM here — stub maps the primary sample into pose + scores so the
owner-fusion *code path* exists and is tested before characterization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from parcel_robot.contracts import (
    SCHEMA_VERSION,
    DetectionMsg,
    EvidenceEnvelopeV1,
    OwnerTrackV1,
    PoseXYZYaw,
    expires_from_ttl,
    identity_covariance,
)
from parcel_robot.uwb.sample import UwbSample

OwnerChannelPrimary = Literal["vision", "uwb"]
OWNER_CHANNEL_PRIMARIES = frozenset({"vision", "uwb"})

DOES_NOT_PROVE = (
    "Fusion stub does not prove field UWB↔vision association or ReID confirm.",
    "Primary-channel choice is a config switch pending P5 characterization (HR-2).",
)


@dataclass(frozen=True, slots=True)
class OwnerFusionConfig:
    """Switchable primary without changing ``OwnerTrackV1``."""

    primary: OwnerChannelPrimary = "uwb"
    # Minimum quality / score to treat the primary sample as usable.
    min_primary_quality: float = 0.35
    # When primary is UWB and vision is also fresh, boost identity slightly.
    corroboration_identity_bonus: float = 0.1
    enrolled_owner_id: str = "owner-1"
    frame_id: str = "odom"
    source: str = "owner_fusion_stub"
    calibration_id: str = "owner-fusion-stub-v1"
    ttl_ns: int = 500_000_000

    def __post_init__(self) -> None:
        if self.primary not in OWNER_CHANNEL_PRIMARIES:
            raise ValueError(f"primary must be one of {sorted(OWNER_CHANNEL_PRIMARIES)}")
        for name, value in (
            ("min_primary_quality", self.min_primary_quality),
            ("corroboration_identity_bonus", self.corroboration_identity_bonus),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        for name, value in (
            ("enrolled_owner_id", self.enrolled_owner_id),
            ("frame_id", self.frame_id),
            ("source", self.source),
            ("calibration_id", self.calibration_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if isinstance(self.ttl_ns, bool) or not isinstance(self.ttl_ns, int) or self.ttl_ns <= 0:
            raise ValueError("ttl_ns must be a positive integer")


@dataclass(frozen=True, slots=True)
class OwnerFusionResult:
    """Stub fusion output: track + which channel actually drove pose."""

    track: OwnerTrackV1 | None
    primary_used: OwnerChannelPrimary | None
    reason: str

    @property
    def accepted(self) -> bool:
        return self.track is not None


def _fresh(sample_envelope: EvidenceEnvelopeV1, now_monotonic_ns: int) -> bool:
    return not sample_envelope.expired(now_monotonic_ns)


def _pose_from_bearing_range(
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    bearing_rad: float,
    range_m: float,
) -> PoseXYZYaw:
    world_yaw = robot_yaw_rad + bearing_rad
    return PoseXYZYaw(
        x=robot_x + range_m * math.cos(world_yaw),
        y=robot_y + range_m * math.sin(world_yaw),
        z=0.0,
        yaw_rad=world_yaw,
    )


def _zero_velocity() -> PoseXYZYaw:
    return PoseXYZYaw(x=0.0, y=0.0, z=0.0, yaw_rad=0.0)


class OwnerFusionStub:
    """Vision × UWB → ``OwnerTrackV1`` with switchable primary (no contract change)."""

    def __init__(self, config: OwnerFusionConfig | None = None) -> None:
        self._config = config if config is not None else OwnerFusionConfig()
        self._sequence = 0

    @property
    def config(self) -> OwnerFusionConfig:
        return self._config

    def with_primary(self, primary: OwnerChannelPrimary) -> OwnerFusionStub:
        """Return a new stub with inverted/switched primary (immutable config)."""

        if primary not in OWNER_CHANNEL_PRIMARIES:
            raise ValueError(f"primary must be one of {sorted(OWNER_CHANNEL_PRIMARIES)}")
        return OwnerFusionStub(
            OwnerFusionConfig(
                primary=primary,
                min_primary_quality=self._config.min_primary_quality,
                corroboration_identity_bonus=self._config.corroboration_identity_bonus,
                enrolled_owner_id=self._config.enrolled_owner_id,
                frame_id=self._config.frame_id,
                source=self._config.source,
                calibration_id=self._config.calibration_id,
                ttl_ns=self._config.ttl_ns,
            )
        )

    def fuse(
        self,
        *,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
        now_monotonic_ns: int,
        uwb: UwbSample | None = None,
        vision: DetectionMsg | None = None,
        transient_track_id: str = "owner-transient-1",
    ) -> OwnerFusionResult:
        """Fail-closed fuse into OwnerTrackV1.

        Primary channel must be present, fresh, and above quality gate.
        Secondary channel may corroborate identity/visibility but never changes
        the OwnerTrackV1 schema.
        """

        cfg = self._config
        if isinstance(now_monotonic_ns, bool) or not isinstance(now_monotonic_ns, int):
            raise TypeError("now_monotonic_ns must be an integer")
        if now_monotonic_ns < 0:
            raise ValueError("now_monotonic_ns must be non-negative")

        uwb_ok = (
            uwb is not None
            and _fresh(uwb.envelope, now_monotonic_ns)
            and uwb.quality >= cfg.min_primary_quality
            and not uwb.multipath_suspect
        )
        vision_ok = (
            vision is not None
            and _fresh(vision.envelope, now_monotonic_ns)
            and vision.score >= cfg.min_primary_quality
        )

        if cfg.primary == "uwb":
            if not uwb_ok:
                return OwnerFusionResult(
                    track=None,
                    primary_used=None,
                    reason="primary_uwb_unavailable",
                )
            assert uwb is not None
            pose = _pose_from_bearing_range(
                robot_x=robot_x,
                robot_y=robot_y,
                robot_yaw_rad=robot_yaw_rad,
                bearing_rad=uwb.bearing_rad,
                range_m=uwb.range_m,
            )
            visibility = uwb.quality
            identity = 0.55 + (cfg.corroboration_identity_bonus if vision_ok else 0.0)
            appearance_refs: tuple[str, ...] = (
                (vision.envelope.evidence_id,) if vision_ok and vision is not None else ()
            )
            state = "confirmed" if vision_ok else "ambiguous"
            primary_used: OwnerChannelPrimary = "uwb"
            provenance = ("owner_fusion_stub_v1", "primary_uwb")
            source_ts = uwb.envelope.source_timestamp_ns
        else:
            if not vision_ok:
                return OwnerFusionResult(
                    track=None,
                    primary_used=None,
                    reason="primary_vision_unavailable",
                )
            assert vision is not None
            pose = _pose_from_bearing_range(
                robot_x=robot_x,
                robot_y=robot_y,
                robot_yaw_rad=robot_yaw_rad,
                bearing_rad=vision.bearing_rad,
                range_m=vision.range_m,
            )
            visibility = vision.score
            identity = 0.7 + (cfg.corroboration_identity_bonus if uwb_ok else 0.0)
            appearance_refs = (vision.envelope.evidence_id,)
            # Vision-primary: confirmed when class is owner, or person+UWB corroborates.
            if vision.class_id == "owner" or (vision.class_id == "person" and uwb_ok):
                state = "confirmed"
            else:
                state = "ambiguous"
            primary_used = "vision"
            provenance = ("owner_fusion_stub_v1", "primary_vision")
            source_ts = vision.envelope.source_timestamp_ns

        identity = max(0.0, min(1.0, identity))
        self._sequence += 1
        envelope = EvidenceEnvelopeV1(
            schema_version=SCHEMA_VERSION,
            evidence_id=f"owner-fuse-{self._sequence}",
            source=cfg.source,
            source_timestamp_ns=source_ts,
            received_monotonic_ns=now_monotonic_ns,
            sequence=self._sequence,
            frame_id=cfg.frame_id,
            scene_revision=0,
            expires_monotonic_ns=expires_from_ttl(
                received_monotonic_ns=now_monotonic_ns, ttl_ns=cfg.ttl_ns
            ),
            calibration_id=cfg.calibration_id,
            provenance=provenance,
        )
        last_confirmed = now_monotonic_ns if state == "confirmed" else 0
        track = OwnerTrackV1(
            envelope=envelope,
            enrolled_owner_id=cfg.enrolled_owner_id,
            transient_track_id=transient_track_id,
            state=state,
            pose=pose,
            pose_covariance=identity_covariance(4, variance=0.25),
            velocity=_zero_velocity(),
            velocity_covariance=identity_covariance(4, variance=1.0),
            identity_score=identity,
            visibility_score=visibility,
            appearance_evidence_refs=appearance_refs,
            last_confirmed_at_monotonic_ns=last_confirmed,
        )
        return OwnerFusionResult(
            track=track,
            primary_used=primary_used,
            reason="ok",
        )
