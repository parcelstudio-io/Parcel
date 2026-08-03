"""Deployment-disabled v8 all-ray projected collision shield.

The legacy collision brake consumes one nearest obstacle.  This experimental
component instead examines every ray in one calibrated, normalized 720-ray
scan and constrains a proposed translational command against every observed
finite return.  Unavailable rays remain explicit because the calibrated ROS
normalizer uses NaN for bins left without external evidence after self-return
removal.  The component also accounts for the travel direction swept by a
simultaneous yaw command during the reaction horizon.

The shield is selected only by the explicit v8 predictive mode; Parcel's
default navigation profile remains unchanged.  The experiment configuration
keeps deployment disabled until a paired protocol promotes it.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

V8_ALL_RAY_PROFILE_ID = "parcel-v8-all-ray-yaw-swept-projected-cap"
V8_ALL_RAY_MODE = "all_ray_yaw_swept_projected_speed_cap"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TWO_PI = 2.0 * math.pi
_V8_FROZEN_NUMERIC_PROFILE = {
    "stop_distance_m": 0.8,
    "reaction_horizon_s": 0.12,
    "control_period_s": 0.1,
    "full_circle_tolerance_rad": 1e-5,
    "closing_epsilon_mps": 1e-9,
    "certificate_tolerance_m": 1e-9,
}


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class V8AllRayShieldConfig:
    """Frozen safety constants for the deployment-disabled v8 treatment."""

    stop_distance_m: float = 0.8
    reaction_horizon_s: float = 0.12
    control_period_s: float = 0.1
    required_ray_count: int = 720
    full_circle_tolerance_rad: float = 1e-5
    closing_epsilon_mps: float = 1e-9
    certificate_tolerance_m: float = 1e-9
    profile_id: str = V8_ALL_RAY_PROFILE_ID

    def __post_init__(self) -> None:
        for name in (
            "stop_distance_m",
            "reaction_horizon_s",
            "control_period_s",
            "full_circle_tolerance_rad",
            "closing_epsilon_mps",
            "certificate_tolerance_m",
        ):
            value = _finite_number(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.reaction_horizon_s + 1e-12 < self.control_period_s:
            raise ValueError("reaction_horizon_s must be at least control_period_s")
        if (
            isinstance(self.required_ray_count, bool)
            or not isinstance(self.required_ray_count, int)
            or self.required_ray_count != 720
        ):
            raise ValueError("the v8 shield requires exactly 720 normalized rays")
        if self.full_circle_tolerance_rad > 1e-3:
            raise ValueError("full_circle_tolerance_rad is too permissive")
        if self.certificate_tolerance_m > 1e-6:
            raise ValueError("certificate_tolerance_m is too permissive")
        if self.profile_id != V8_ALL_RAY_PROFILE_ID:
            raise ValueError("unexpected v8 all-ray profile identity")
        for name, expected in _V8_FROZEN_NUMERIC_PROFILE.items():
            if float(getattr(self, name)) != expected:
                raise ValueError(f"v8 profile requires {name}={expected!r}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> V8AllRayShieldConfig:
        """Load an exact component block without accepting silent defaults."""

        expected = {
            "stop_distance_m",
            "reaction_horizon_s",
            "control_period_s",
            "required_ray_count",
            "full_circle_tolerance_rad",
            "closing_epsilon_mps",
            "certificate_tolerance_m",
            "profile_id",
        }
        if set(value) != expected:
            raise ValueError(
                "v8 all-ray config fields changed: "
                f"expected {sorted(expected)!r}, got {sorted(value)!r}"
            )
        ray_count = value["required_ray_count"]
        if isinstance(ray_count, bool) or not isinstance(ray_count, int):
            raise TypeError("required_ray_count must be an integer")
        profile_id = value["profile_id"]
        if not isinstance(profile_id, str):
            raise TypeError("profile_id must be a string")
        return cls(
            stop_distance_m=_finite_number(value["stop_distance_m"], "stop_distance_m"),
            reaction_horizon_s=_finite_number(value["reaction_horizon_s"], "reaction_horizon_s"),
            control_period_s=_finite_number(value["control_period_s"], "control_period_s"),
            required_ray_count=ray_count,
            full_circle_tolerance_rad=_finite_number(
                value["full_circle_tolerance_rad"], "full_circle_tolerance_rad"
            ),
            closing_epsilon_mps=_finite_number(value["closing_epsilon_mps"], "closing_epsilon_mps"),
            certificate_tolerance_m=_finite_number(
                value["certificate_tolerance_m"], "certificate_tolerance_m"
            ),
            profile_id=profile_id,
        )


@dataclass(frozen=True, slots=True)
class V8ActionCertificate:
    """Evaluator-recomputable observed-return evidence for one final action."""

    schema_version: int
    profile_id: str
    scan_sha256: str
    action_sha256: str
    ray_count: int
    examined_ray_count: int
    finite_return_count: int
    clear_ray_count: int
    unavailable_ray_count: int
    perception_available: bool
    perception_complete: bool
    boundary_scope: str
    positive_closing_return_count: int
    violating_return_count: int
    minimum_projected_margin_m: float | None
    limiting_ray_index: int | None
    limiting_range_m: float | None
    limiting_bearing_rad: float | None
    limiting_maximum_closing_speed_mps: float | None
    stop_distance_m: float
    reaction_horizon_s: float
    control_period_s: float
    heading_sweep_rad: float
    observed_return_boundary_satisfied: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
            or self.profile_id != V8_ALL_RAY_PROFILE_ID
        ):
            raise ValueError("unsupported v8 action-certificate identity")
        if not _SHA256.fullmatch(self.scan_sha256) or not _SHA256.fullmatch(self.action_sha256):
            raise ValueError("v8 certificate digests must be lowercase SHA-256 values")
        counts = (
            self.ray_count,
            self.examined_ray_count,
            self.finite_return_count,
            self.clear_ray_count,
            self.unavailable_ray_count,
            self.positive_closing_return_count,
            self.violating_return_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
        ):
            raise ValueError("v8 certificate counters must be non-negative integers")
        if self.ray_count != 720 or self.examined_ray_count != self.ray_count:
            raise ValueError("v8 certificate must attest all 720 normalized rays")
        if (
            self.finite_return_count + self.clear_ray_count + self.unavailable_ray_count
            != self.ray_count
        ):
            raise ValueError("v8 certificate ray classifications do not cover the scan")
        if not (
            self.violating_return_count
            <= self.positive_closing_return_count
            <= self.finite_return_count
        ):
            raise ValueError("v8 certificate closing-return counters are inconsistent")
        if (
            not isinstance(self.perception_available, bool)
            or not isinstance(self.perception_complete, bool)
            or not isinstance(self.observed_return_boundary_satisfied, bool)
        ):
            raise TypeError("v8 certificate state flags must be booleans")
        if self.perception_available != (self.finite_return_count + self.clear_ray_count > 0):
            raise ValueError("v8 certificate perception availability is inconsistent")
        if self.perception_complete != (self.unavailable_ray_count == 0):
            raise ValueError("v8 certificate perception completeness is inconsistent")
        if self.boundary_scope != "observed_finite_returns_only":
            raise ValueError("v8 certificate boundary scope is invalid")
        if self.observed_return_boundary_satisfied != (self.violating_return_count == 0):
            raise ValueError("v8 certificate observed-return boundary result is inconsistent")
        for name, expected in (
            ("stop_distance_m", _V8_FROZEN_NUMERIC_PROFILE["stop_distance_m"]),
            ("reaction_horizon_s", _V8_FROZEN_NUMERIC_PROFILE["reaction_horizon_s"]),
            ("control_period_s", _V8_FROZEN_NUMERIC_PROFILE["control_period_s"]),
        ):
            if _finite_number(getattr(self, name), name) != expected:
                raise ValueError(f"v8 certificate requires {name}={expected!r}")
        _finite_number(self.heading_sweep_rad, "heading_sweep_rad")
        limiting_values = (
            self.minimum_projected_margin_m,
            self.limiting_ray_index,
            self.limiting_range_m,
            self.limiting_bearing_rad,
            self.limiting_maximum_closing_speed_mps,
        )
        if self.positive_closing_return_count == 0:
            if any(value is not None for value in limiting_values):
                raise ValueError("v8 certificate has a limit without a closing return")
        else:
            if any(value is None for value in limiting_values):
                raise ValueError("v8 certificate is missing its limiting return")
            if (
                isinstance(self.limiting_ray_index, bool)
                or not isinstance(self.limiting_ray_index, int)
                or not 0 <= self.limiting_ray_index < self.ray_count
            ):
                raise ValueError("v8 certificate limiting ray index is invalid")
            assert self.minimum_projected_margin_m is not None
            assert self.limiting_range_m is not None
            assert self.limiting_bearing_rad is not None
            assert self.limiting_maximum_closing_speed_mps is not None
            _finite_number(self.minimum_projected_margin_m, "minimum_projected_margin_m")
            limiting_range = _finite_number(self.limiting_range_m, "limiting_range_m")
            _finite_number(self.limiting_bearing_rad, "limiting_bearing_rad")
            limiting_speed = _finite_number(
                self.limiting_maximum_closing_speed_mps,
                "limiting_maximum_closing_speed_mps",
            )
            if limiting_range < 0.0 or limiting_speed <= 0.0:
                raise ValueError("v8 certificate limiting return is invalid")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class V8ShieldDecision:
    """One direction-preserving shield decision and its independent certificate."""

    requested_vx_mps: float
    requested_vy_mps: float
    requested_yaw_rate_rps: float
    output_vx_mps: float
    output_vy_mps: float
    output_yaw_rate_rps: float
    preexisting_scale_limit: float
    all_ray_scale_limit: float
    applied_scale: float
    positive_closing_return_count: int
    limiting_ray_index: int | None
    limiting_range_m: float | None
    limiting_bearing_rad: float | None
    limiting_maximum_closing_speed_mps: float | None
    note: str
    certificate: V8ActionCertificate

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _prepare_scan(
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    config: V8AllRayShieldConfig,
) -> tuple[tuple[float, ...], float, float]:
    if isinstance(ranges_m, (str, bytes)):
        raise TypeError("ranges_m must be a numeric sequence")
    try:
        raw_ranges = tuple(ranges_m)
    except TypeError as exc:
        raise TypeError("ranges_m must be a numeric sequence") from exc
    if len(raw_ranges) != config.required_ray_count:
        raise ValueError(
            f"v8 shield requires {config.required_ray_count} rays, got {len(raw_ranges)}"
        )
    angle_min = _finite_number(angle_min_rad, "angle_min_rad")
    angle_increment = _finite_number(angle_increment_rad, "angle_increment_rad")
    if angle_increment <= 0.0:
        raise ValueError("angle_increment_rad must be positive")
    angular_coverage = (len(raw_ranges) - 1) * angle_increment
    if not math.isclose(
        angular_coverage,
        _TWO_PI,
        rel_tol=0.0,
        abs_tol=config.full_circle_tolerance_rad,
    ):
        raise ValueError("v8 shield requires a normalized full-circle scan")

    normalized: list[float] = []
    for index, raw in enumerate(raw_ranges):
        if isinstance(raw, bool):
            raise TypeError(f"range {index} must be numeric")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"range {index} must be numeric") from exc
        if value == math.inf or math.isnan(value):
            normalized.append(value)
            continue
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"range {index} must be non-negative, NaN, or positive infinity")
        normalized.append(value)
    return tuple(normalized), angle_min, angle_increment


def _shield_swept_closing_speed(
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
    reaction_horizon_s: float,
    bearing_rad: float,
) -> float:
    """Analytically bound closing speed while the body velocity heading sweeps."""

    speed = math.hypot(vx_mps, vy_mps)
    if speed <= 0.0:
        return 0.0
    start_heading = math.atan2(vy_mps, vx_mps)
    end_heading = start_heading + yaw_rate_rps * reaction_horizon_s
    lower = min(start_heading, end_heading)
    upper = max(start_heading, end_heading)
    first_alignment = bearing_rad + math.ceil((lower - bearing_rad) / _TWO_PI) * _TWO_PI
    if first_alignment <= upper + 1e-15:
        return speed
    endpoint_cosine = max(
        math.cos(start_heading - bearing_rad),
        math.cos(end_heading - bearing_rad),
        0.0,
    )
    return speed * endpoint_cosine


def _certificate_swept_closing_speed(
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
    reaction_horizon_s: float,
    bearing_rad: float,
) -> float:
    """Independently express the same bound using directed phase travel."""

    speed = math.hypot(vx_mps, vy_mps)
    if speed <= 0.0:
        return 0.0
    start_phase = (math.atan2(vy_mps, vx_mps) - bearing_rad) % _TWO_PI
    sweep = yaw_rate_rps * reaction_horizon_s
    if abs(sweep) >= _TWO_PI:
        maximum_cosine = 1.0
    elif sweep >= 0.0:
        distance_to_alignment = (-start_phase) % _TWO_PI
        maximum_cosine = (
            1.0
            if distance_to_alignment <= sweep + 1e-15
            else max(math.cos(start_phase), math.cos(start_phase + sweep), 0.0)
        )
    else:
        distance_to_alignment = start_phase % _TWO_PI
        maximum_cosine = (
            1.0
            if distance_to_alignment <= -sweep + 1e-15
            else max(math.cos(start_phase), math.cos(start_phase + sweep), 0.0)
        )
    return speed * maximum_cosine


def _scan_sha256(ranges: Sequence[float], angle_min: float, angle_increment: float) -> str:
    digest = hashlib.sha256()
    digest.update(b"parcel-v8-normalized-scan-v1\x00")
    digest.update(struct.pack("<Idd", len(ranges), angle_min, angle_increment))
    for value in ranges:
        if math.isnan(value):
            digest.update(b"N")
        elif value == math.inf:
            digest.update(b"I")
        else:
            digest.update(b"F")
            digest.update(struct.pack("<d", value))
    return digest.hexdigest()


def _action_sha256(vx_mps: float, vy_mps: float, yaw_rate_rps: float) -> str:
    digest = hashlib.sha256()
    digest.update(b"parcel-v8-shielded-action-v1\x00")
    digest.update(struct.pack("<ddd", vx_mps, vy_mps, yaw_rate_rps))
    return digest.hexdigest()


def certify_v8_all_ray_action(
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    config: V8AllRayShieldConfig | None = None,
) -> V8ActionCertificate:
    """Recompute the all-ray invariant from a final action and raw public inputs."""

    profile = config or V8AllRayShieldConfig()
    vx = _finite_number(vx_mps, "vx_mps")
    vy = _finite_number(vy_mps, "vy_mps")
    yaw_rate = _finite_number(yaw_rate_rps, "yaw_rate_rps")
    ranges, angle_min, angle_increment = _prepare_scan(
        ranges_m,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        config=profile,
    )

    finite_count = 0
    clear_count = 0
    unavailable_count = 0
    positive_closing_count = 0
    violating_count = 0
    minimum_margin: float | None = None
    limiting_index: int | None = None
    limiting_range: float | None = None
    limiting_bearing: float | None = None
    limiting_closing_speed: float | None = None
    for index, distance in enumerate(ranges):
        if distance == math.inf:
            clear_count += 1
            continue
        if math.isnan(distance):
            unavailable_count += 1
            continue
        finite_count += 1
        bearing = angle_min + index * angle_increment
        closing_speed = _certificate_swept_closing_speed(
            vx,
            vy,
            yaw_rate,
            profile.reaction_horizon_s,
            bearing,
        )
        if closing_speed <= profile.closing_epsilon_mps:
            continue
        positive_closing_count += 1
        margin = distance - profile.stop_distance_m - profile.reaction_horizon_s * closing_speed
        if margin < -profile.certificate_tolerance_m:
            violating_count += 1
        if minimum_margin is None or margin < minimum_margin:
            minimum_margin = margin
            limiting_index = index
            limiting_range = distance
            limiting_bearing = bearing
            limiting_closing_speed = closing_speed

    return V8ActionCertificate(
        schema_version=1,
        profile_id=profile.profile_id,
        scan_sha256=_scan_sha256(ranges, angle_min, angle_increment),
        action_sha256=_action_sha256(vx, vy, yaw_rate),
        ray_count=len(ranges),
        examined_ray_count=len(ranges),
        finite_return_count=finite_count,
        clear_ray_count=clear_count,
        unavailable_ray_count=unavailable_count,
        perception_available=finite_count + clear_count > 0,
        perception_complete=unavailable_count == 0,
        boundary_scope="observed_finite_returns_only",
        positive_closing_return_count=positive_closing_count,
        violating_return_count=violating_count,
        minimum_projected_margin_m=minimum_margin,
        limiting_ray_index=limiting_index,
        limiting_range_m=limiting_range,
        limiting_bearing_rad=limiting_bearing,
        limiting_maximum_closing_speed_mps=limiting_closing_speed,
        stop_distance_m=profile.stop_distance_m,
        reaction_horizon_s=profile.reaction_horizon_s,
        control_period_s=profile.control_period_s,
        heading_sweep_rad=yaw_rate * profile.reaction_horizon_s,
        observed_return_boundary_satisfied=violating_count == 0,
    )


def verify_v8_all_ray_action_certificate(
    certificate: V8ActionCertificate,
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    config: V8AllRayShieldConfig | None = None,
) -> V8ActionCertificate:
    """Fail closed unless a stored certificate exactly matches recomputation."""

    if not isinstance(certificate, V8ActionCertificate):
        raise TypeError("certificate must be a V8ActionCertificate")
    expected = certify_v8_all_ray_action(
        vx_mps,
        vy_mps,
        yaw_rate_rps,
        ranges_m,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        config=config,
    )
    if certificate != expected:
        raise ValueError("v8 action certificate does not match independent recomputation")
    return expected


def apply_v8_all_ray_shield(
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    preexisting_scale_limit: float = 1.0,
    config: V8AllRayShieldConfig | None = None,
) -> V8ShieldDecision:
    """Apply the minimum yaw-swept cap across every normalized scan ray.

    ``preexisting_scale_limit`` composes person, comfort, or other restrictions
    relative to the same proposed command.  Taking the minimum guarantees this
    shield never weakens an existing restriction.
    """

    profile = config or V8AllRayShieldConfig()
    vx = _finite_number(vx_mps, "vx_mps")
    vy = _finite_number(vy_mps, "vy_mps")
    yaw_rate = _finite_number(yaw_rate_rps, "yaw_rate_rps")
    prior_scale = _finite_number(preexisting_scale_limit, "preexisting_scale_limit")
    if not 0.0 <= prior_scale <= 1.0:
        raise ValueError("preexisting_scale_limit must be in [0, 1]")
    ranges, angle_min, angle_increment = _prepare_scan(
        ranges_m,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        config=profile,
    )

    all_ray_scale = 1.0
    positive_closing_count = 0
    limiting_index: int | None = None
    limiting_range: float | None = None
    limiting_bearing: float | None = None
    limiting_closing_speed: float | None = None
    finite_or_clear_count = 0
    for index, distance in enumerate(ranges):
        if distance == math.inf:
            finite_or_clear_count += 1
            continue
        if math.isnan(distance):
            continue
        finite_or_clear_count += 1
        bearing = angle_min + index * angle_increment
        closing_speed = _shield_swept_closing_speed(
            vx,
            vy,
            yaw_rate,
            profile.reaction_horizon_s,
            bearing,
        )
        if closing_speed <= profile.closing_epsilon_mps:
            continue
        positive_closing_count += 1
        available_distance = max(0.0, distance - profile.stop_distance_m)
        ray_scale = min(
            1.0,
            available_distance / (profile.reaction_horizon_s * closing_speed),
        )
        if ray_scale < all_ray_scale:
            all_ray_scale = ray_scale
            limiting_index = index
            limiting_range = distance
            limiting_bearing = bearing
            limiting_closing_speed = closing_speed

    perception_available = finite_or_clear_count > 0
    perception_complete = finite_or_clear_count == len(ranges)
    applied_scale = min(prior_scale, all_ray_scale) if perception_available else 0.0
    if applied_scale <= 0.0:
        output_vx = 0.0
        output_vy = 0.0
    else:
        output_vx = vx * applied_scale
        output_vy = vy * applied_scale

    certificate = certify_v8_all_ray_action(
        output_vx,
        output_vy,
        yaw_rate,
        ranges,
        angle_min_rad=angle_min,
        angle_increment_rad=angle_increment,
        config=profile,
    )
    if not certificate.observed_return_boundary_satisfied:
        raise RuntimeError("v8 shield output failed independent observed-return certification")

    if not perception_available:
        note = "all_ray_perception_unavailable_stop"
    elif not perception_complete:
        note = "all_ray_observed_returns_only_incomplete_scan"
    elif math.hypot(vx, vy) <= profile.closing_epsilon_mps:
        note = "all_ray_no_translation"
    elif all_ray_scale <= 0.0:
        note = "all_ray_hard_boundary_stop"
    elif all_ray_scale < prior_scale:
        note = "all_ray_yaw_swept_projected_cap"
    elif prior_scale < 1.0:
        note = "all_ray_preexisting_scale_preserved"
    else:
        note = "all_ray_clear"

    return V8ShieldDecision(
        requested_vx_mps=vx,
        requested_vy_mps=vy,
        requested_yaw_rate_rps=yaw_rate,
        output_vx_mps=output_vx,
        output_vy_mps=output_vy,
        output_yaw_rate_rps=yaw_rate,
        preexisting_scale_limit=prior_scale,
        all_ray_scale_limit=all_ray_scale,
        applied_scale=applied_scale,
        positive_closing_return_count=positive_closing_count,
        limiting_ray_index=limiting_index,
        limiting_range_m=limiting_range,
        limiting_bearing_rad=limiting_bearing,
        limiting_maximum_closing_speed_mps=limiting_closing_speed,
        note=note,
        certificate=certificate,
    )


__all__ = [
    "V8_ALL_RAY_MODE",
    "V8_ALL_RAY_PROFILE_ID",
    "V8ActionCertificate",
    "V8AllRayShieldConfig",
    "V8ShieldDecision",
    "apply_v8_all_ray_shield",
    "certify_v8_all_ray_action",
    "verify_v8_all_ray_action_certificate",
]
