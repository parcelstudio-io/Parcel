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

The pixel re-ID input seam (card P1-C)
--------------------------------------
Until P1-C the ``identity_score`` on the emitted track was a **channel prior**:
0.55 for UWB-primary, 0.7 for vision-primary, plus a corroboration bonus. Those
constants describe how much this module trusts a *channel*, which is not the
same question as how much it believes *this is the owner* — and the audit's
finding was that nothing downstream could tell the difference, because the only
producer in the tree fed a mocap body at 1.0.

:class:`PixelTrackInput` is the seam that makes the number a measurement.
``parcel_robot.owner_tracking`` embeds the person crop, scores it against the
owner's enrolled gallery, and hands the cosine here. When one is supplied:

* ``identity_score`` is the pixel channel's measured similarity, never a prior;
* ``confirmed`` requires ``owner_claim`` — a gallery-backed match, not merely a
  fresh channel;
* ``PixelTrackInput`` itself refuses to exist with ``owner_claim`` set while
  ``gallery_enrolled`` is false, so "owner with an empty gallery" is
  unrepresentable rather than merely unlikely.

**Passing no ``pixel`` changes nothing.** Every pre-P1-C call site produces the
identical track it did before; the seam is additive and pinned that way by
``tests/test_p1c_owner_fusion_seam.py``. The pixel channel supplies IDENTITY
only — it never makes an unavailable primary available, because it carries no
pose of its own.
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
    (
        "A supplied PixelTrackInput carries a measured cosine; whether its "
        "BOUNDARY was measured is a separate fact, and it is gallery_calibrated "
        "(card P1-C). An uncalibrated gallery was measured claiming a stranger."
    ),
    (
        "No P1-C operating point has been measured on a real camera or on real "
        "people — only on a synthesized two-person clip."
    ),
)


@dataclass(frozen=True, slots=True)
class PixelTrackInput:
    """Card P1-C. The pixel re-ID channel's measured say on WHO this is.

    Deliberately declared here and not imported from
    ``parcel_robot.owner_tracking``: this module is the *seam*, and a seam that
    imports its producer is a dependency, not a seam. ``owner_tracking`` builds
    one of these through ``PixelOwnerTrack.as_fusion_input()``; anything else
    that can measure an identity similarity may build one too.

    Carries no pose. That is the whole design: pose comes from the primary
    channel (UWB range/bearing, or a vision ``DetectionMsg``), identity comes
    from here, and neither can be substituted for the other.
    """

    #: The tracker's own short-horizon id. Survives an occlusion; that is what
    #: makes reacquisition a *reacquisition* and not a new stranger.
    transient_track_id: str
    #: Measured cosine against the enrolled gallery, clamped into [0, 1] by the
    #: producer because ``OwnerTrackV1.identity_score`` is a probability field.
    identity_similarity: float
    #: The detector's confidence that a person is there at all. A different
    #: question from identity, and kept a different field for that reason.
    visibility: float
    #: True only when the gallery floor AND the discriminative margin were both
    #: met this frame. See ``owner_tracking.tracker._score_identity``.
    owner_claim: bool
    #: False when nobody has enrolled an appearance. The invariant below is the
    #: contract-level form of card P1-C's "zero owner claims with an empty
    #: gallery" row: it is not a policy this module applies, it is a state this
    #: type cannot hold.
    gallery_enrolled: bool
    #: False when the gallery's operating point was DERIVED from the owner's own
    #: crops instead of measured against a known non-owner. The claim is still a
    #: measurement; its boundary is not. Kept a separate field rather than
    #: discounted into ``identity_similarity``, because a reader who wants the
    #: cosine should get the cosine, and a reader who wants to know how much to
    #: trust the boundary should have to ask for that separately.
    gallery_calibrated: bool = False
    appearance_evidence_refs: tuple[str, ...] = ()
    source_timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.transient_track_id, str) or not self.transient_track_id.strip():
            raise ValueError("transient_track_id must be a non-empty string")
        for name in ("identity_similarity", "visibility"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            number = float(value)
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"{name} must be a finite value in [0, 1]")
            object.__setattr__(self, name, number)
        for name in ("owner_claim", "gallery_enrolled", "gallery_calibrated"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if self.gallery_calibrated and not self.gallery_enrolled:
            raise ValueError("gallery_calibrated without gallery_enrolled is not a state")
        if self.owner_claim and not self.gallery_enrolled:
            raise ValueError(
                "owner_claim without gallery_enrolled: an owner cannot be "
                "recognised against a gallery nobody enrolled (card P1-C)"
            )
        refs = tuple(str(ref) for ref in self.appearance_evidence_refs)
        if len(refs) > 16:
            raise ValueError("appearance_evidence_refs is capped at 16 entries")
        object.__setattr__(self, "appearance_evidence_refs", refs)
        if (
            isinstance(self.source_timestamp_ns, bool)
            or not isinstance(self.source_timestamp_ns, int)
            or self.source_timestamp_ns < 0
        ):
            raise ValueError("source_timestamp_ns must be a non-negative integer")


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
    #: Card P1-C. ``channel_prior`` — the identity score is this module's
    #: hard-coded trust in the channel that supplied pose. ``pixel_reid`` — it
    #: is a cosine somebody measured against an enrolled gallery. A reader who
    #: does not check this field cannot tell the two apart from the number, and
    #: telling them apart is the point of the card.
    identity_source: str = "channel_prior"

    @property
    def accepted(self) -> bool:
        return self.track is not None

    @property
    def identity_measured(self) -> bool:
        return self.identity_source.startswith("pixel_reid")

    @property
    def identity_calibrated(self) -> bool:
        return self.identity_source == "pixel_reid"


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
        pixel: PixelTrackInput | None = None,
        transient_track_id: str = "owner-transient-1",
    ) -> OwnerFusionResult:
        """Fail-closed fuse into OwnerTrackV1.

        Primary channel must be present, fresh, and above quality gate.
        Secondary channel may corroborate identity/visibility but never changes
        the OwnerTrackV1 schema.

        ``pixel`` (card P1-C) is the re-ID input seam. It supplies IDENTITY and
        nothing else: it cannot make an absent primary available, it cannot move
        pose, and omitting it reproduces the pre-P1-C output exactly.
        """

        cfg = self._config
        if pixel is not None and not isinstance(pixel, PixelTrackInput):
            raise TypeError("pixel must be a PixelTrackInput or None")
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

        # ---- card P1-C: the pixel re-ID channel overrides the channel prior.
        # Placed AFTER both branches so exactly one rule applies to both
        # primaries, and so the pre-card code above is untouched when no pixel
        # track is supplied (the back-compat row in P1C_STATUS.md).
        identity_source = "channel_prior"
        if pixel is not None:
            identity_source = (
                "pixel_reid" if pixel.gallery_calibrated else "pixel_reid_uncalibrated"
            )
            corroborated = uwb_ok if cfg.primary == "vision" else vision_ok
            identity = pixel.identity_similarity + (
                cfg.corroboration_identity_bonus if corroborated else 0.0
            )
            # A measured similarity that did not clear the gallery's own
            # operating point is not a confirmation, however fresh the pose
            # channel is. This is the one place the card moves an existing
            # verdict, and it moves it strictly toward "I am not sure".
            state = "confirmed" if pixel.owner_claim else "ambiguous"
            appearance_refs = tuple(
                dict.fromkeys((*appearance_refs, *pixel.appearance_evidence_refs))
            )[:16]
            transient_track_id = pixel.transient_track_id

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
            identity_source=identity_source,
        )
