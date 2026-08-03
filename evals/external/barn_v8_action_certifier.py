"""Evaluator-owned certificates for the experimental BARN v8 action boundary.

This module deliberately re-expresses the v8 boundary mathematics without
importing the candidate policy or its collision-shield implementation.  It
examines the final command published at the BARN policy boundary and every bin
of the corresponding normalized scan.  Policy notes and policy-produced
certificates are not inputs and therefore cannot influence the result.

The certified property is deliberately narrow.  For each *finite observed*
return with positive closing motion, the checker requires::

    range - stop_distance
        - reaction_horizon * max_projected_closing_speed_over_heading_sweep
        >= -certificate_tolerance

NaN bins are unavailable evidence, while positive infinity is an observed
clear ray.  The certificate explicitly excludes unavailable directions,
angular gaps between discrete rays, moving objects, and robot geometry or a
swept footprint.  Those exclusions prevent this point-return check from being
misrepresented as a general collision-safety proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

BARN_V8_CERTIFIER_ID = "parcel-barn-v8-independent-action-certifier-v1"
BARN_V8_PROFILE_ID = "parcel-v8-all-ray-yaw-swept-projected-cap"
BARN_V8_BOUNDARY_ALGORITHM_ID = (
    "reaction-horizon-times-max-positive-projection-over-signed-heading-sweep-v1"
)
BARN_V8_BOUNDARY_SCOPE = "observed_finite_returns_only"
BARN_V8_BOUNDARY_RULE_SCOPE = "positive_swept_closing_observed_finite_returns"
BARN_V8_UNCERTIFIED_DOMAINS = (
    "unavailable_nan_directions",
    "angular_space_between_discrete_scan_rays",
    "objects_moving_during_reaction_horizon",
    "robot_geometry_or_swept_footprint",
)

_TWO_PI = 2.0 * math.pi
_ALIGNMENT_EPSILON_RAD = 1e-15


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class V8BarnEvaluatorProfile:
    """Exact immutable identity of the evaluator's accepted v8 profile."""

    schema_version: int = 1
    certifier_id: str = BARN_V8_CERTIFIER_ID
    profile_id: str = BARN_V8_PROFILE_ID
    boundary_algorithm_id: str = BARN_V8_BOUNDARY_ALGORITHM_ID
    stop_distance_m: float = 0.8
    reaction_horizon_s: float = 0.12
    control_period_s: float = 0.1
    required_ray_count: int = 720
    expected_angle_min_rad: float = -math.pi
    expected_angular_coverage_rad: float = _TWO_PI
    scan_geometry_tolerance_rad: float = 1e-5
    closing_epsilon_mps: float = 1e-9
    certificate_tolerance_m: float = 1e-9
    required_lateral_velocity_mps: float = 0.0

    def __post_init__(self) -> None:
        expected: dict[str, str | int | float] = {
            "schema_version": 1,
            "certifier_id": BARN_V8_CERTIFIER_ID,
            "profile_id": BARN_V8_PROFILE_ID,
            "boundary_algorithm_id": BARN_V8_BOUNDARY_ALGORITHM_ID,
            "stop_distance_m": 0.8,
            "reaction_horizon_s": 0.12,
            "control_period_s": 0.1,
            "required_ray_count": 720,
            "expected_angle_min_rad": -math.pi,
            "expected_angular_coverage_rad": _TWO_PI,
            "scan_geometry_tolerance_rad": 1e-5,
            "closing_epsilon_mps": 1e-9,
            "certificate_tolerance_m": 1e-9,
            "required_lateral_velocity_mps": 0.0,
        }
        for name, expected_value in expected.items():
            actual = getattr(self, name)
            if isinstance(expected_value, float):
                if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                    raise TypeError(f"{name} must be numeric")
                if float(actual) != expected_value:
                    raise ValueError(f"v8 evaluator profile requires {name}={expected_value!r}")
            elif actual != expected_value or type(actual) is not type(expected_value):
                raise ValueError(f"v8 evaluator profile requires {name}={expected_value!r}")

    def identity_payload(self) -> dict[str, Any]:
        """Return all behavior-affecting profile fields in canonical form."""

        return asdict(self)

    @property
    def identity_sha256(self) -> str:
        payload = json.dumps(
            self.identity_payload(),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


FROZEN_V8_BARN_EVALUATOR_PROFILE = V8BarnEvaluatorProfile()


@dataclass(frozen=True, slots=True)
class V8BarnActionCertificate:
    """Independent, evaluator-owned evidence for one published BARN action."""

    schema_version: int
    certifier_id: str
    profile_id: str
    profile_sha256: str
    boundary_algorithm_id: str
    boundary_scope: str
    boundary_rule_scope: str
    uncertified_domains: tuple[str, ...]
    scan_sha256: str
    action_sha256: str
    ray_count: int
    examined_ray_count: int
    finite_return_count: int
    clear_ray_count: int
    unavailable_ray_count: int
    perception_available: bool
    perception_complete: bool
    positive_closing_return_count: int
    violating_return_count: int
    minimum_projected_margin_m: float | None
    maximum_observed_closing_speed_mps: float
    maximum_swept_projected_displacement_m: float
    limiting_ray_index: int | None
    limiting_range_m: float | None
    limiting_bearing_rad: float | None
    limiting_maximum_closing_speed_mps: float | None
    stop_distance_m: float
    reaction_horizon_s: float
    control_period_s: float
    angle_min_rad: float
    angle_increment_rad: float
    heading_sweep_rad: float
    published_vx_mps: float
    published_vy_mps: float
    published_yaw_rate_rps: float
    observed_return_boundary_satisfied: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _prepare_normalized_scan(
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    profile: V8BarnEvaluatorProfile,
) -> tuple[tuple[float, ...], float, float]:
    if isinstance(ranges_m, (str, bytes)) or not isinstance(ranges_m, Sequence):
        raise TypeError("ranges_m must be a numeric sequence")
    raw_ranges = tuple(ranges_m)
    if len(raw_ranges) != profile.required_ray_count:
        raise ValueError(
            f"v8 BARN certificate requires exactly {profile.required_ray_count} rays, "
            f"got {len(raw_ranges)}"
        )

    angle_min = _finite_number(angle_min_rad, "angle_min_rad")
    angle_increment = _finite_number(angle_increment_rad, "angle_increment_rad")
    if angle_increment <= 0.0:
        raise ValueError("angle_increment_rad must be positive")
    if not math.isclose(
        angle_min,
        profile.expected_angle_min_rad,
        rel_tol=0.0,
        abs_tol=profile.scan_geometry_tolerance_rad,
    ):
        raise ValueError("v8 BARN certificate requires the calibrated -pi scan origin")
    coverage = (len(raw_ranges) - 1) * angle_increment
    if not math.isclose(
        coverage,
        profile.expected_angular_coverage_rad,
        rel_tol=0.0,
        abs_tol=profile.scan_geometry_tolerance_rad,
    ):
        raise ValueError("v8 BARN certificate requires calibrated full-circle coverage")

    normalized: list[float] = []
    for index, raw in enumerate(raw_ranges):
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"range {index} must be numeric")
        value = float(raw)
        if math.isnan(value) or value == math.inf:
            normalized.append(value)
            continue
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"range {index} must be non-negative, NaN, or positive infinity"
            )
        normalized.append(value)
    return tuple(normalized), angle_min, angle_increment


def _maximum_swept_closing_speed(
    vx_mps: float,
    yaw_rate_rps: float,
    reaction_horizon_s: float,
    bearing_rad: float,
) -> float:
    """Return the analytic max positive ray projection over a signed yaw sweep."""

    speed = abs(vx_mps)
    if speed == 0.0:
        return 0.0

    # A negative body-forward command points along pi at the start, then that
    # velocity direction follows the same signed body-yaw sweep.
    start_heading = 0.0 if vx_mps > 0.0 else math.pi
    start_phase = start_heading - bearing_rad
    end_phase = start_phase + yaw_rate_rps * reaction_horizon_s
    lower_phase = min(start_phase, end_phase)
    upper_phase = max(start_phase, end_phase)

    # cos(phase) reaches one exactly when the swept interval contains any 2pi
    # multiple.  Checking integer bounds preserves the sign of the yaw sweep
    # without sampling or discretizing it.
    first_alignment = math.ceil(
        (lower_phase - _ALIGNMENT_EPSILON_RAD) / _TWO_PI
    )
    last_alignment = math.floor(
        (upper_phase + _ALIGNMENT_EPSILON_RAD) / _TWO_PI
    )
    if first_alignment <= last_alignment:
        maximum_projection = 1.0
    else:
        maximum_projection = max(
            math.cos(start_phase),
            math.cos(end_phase),
            0.0,
        )
    return speed * maximum_projection


def _scan_sha256(ranges: Sequence[float], angle_min: float, angle_increment: float) -> str:
    digest = hashlib.sha256()
    digest.update(b"parcel-barn-v8-evaluator-normalized-scan-v1\x00")
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


def _action_sha256(
    vx_mps: float,
    yaw_rate_rps: float,
    control_period_s: float,
) -> str:
    digest = hashlib.sha256()
    digest.update(b"parcel-barn-v8-evaluator-published-action-v1\x00")
    digest.update(struct.pack("<dddd", vx_mps, 0.0, yaw_rate_rps, control_period_s))
    return digest.hexdigest()


def certify_v8_published_barn_action(
    vx_mps: float,
    yaw_rate_rps: float,
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    control_period_s: float,
    profile: V8BarnEvaluatorProfile | None = None,
) -> V8BarnActionCertificate:
    """Independently check one final ``(vx, vy=0, yaw)`` BARN command.

    The caller must pass the actual normalized scan and final published action;
    there is intentionally no argument for a policy note or policy certificate.
    """

    evaluated_profile = profile or FROZEN_V8_BARN_EVALUATOR_PROFILE
    if not isinstance(evaluated_profile, V8BarnEvaluatorProfile):
        raise TypeError("profile must be a V8BarnEvaluatorProfile")
    vx = _finite_number(vx_mps, "vx_mps")
    yaw_rate = _finite_number(yaw_rate_rps, "yaw_rate_rps")
    control_period = _finite_number(control_period_s, "control_period_s")
    if not math.isclose(
        control_period,
        evaluated_profile.control_period_s,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("published action control period does not match the v8 profile")
    ranges, angle_min, angle_increment = _prepare_normalized_scan(
        ranges_m,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        profile=evaluated_profile,
    )

    finite_count = 0
    clear_count = 0
    unavailable_count = 0
    positive_closing_count = 0
    violating_count = 0
    minimum_margin: float | None = None
    maximum_closing_speed = 0.0
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
        closing_speed = _maximum_swept_closing_speed(
            vx,
            yaw_rate,
            evaluated_profile.reaction_horizon_s,
            bearing,
        )
        if closing_speed <= evaluated_profile.closing_epsilon_mps:
            continue

        positive_closing_count += 1
        maximum_closing_speed = max(maximum_closing_speed, closing_speed)
        projected_displacement = evaluated_profile.reaction_horizon_s * closing_speed
        margin = distance - evaluated_profile.stop_distance_m - projected_displacement
        if margin < -evaluated_profile.certificate_tolerance_m:
            violating_count += 1
        if minimum_margin is None or margin < minimum_margin:
            minimum_margin = margin
            limiting_index = index
            limiting_range = distance
            limiting_bearing = bearing
            limiting_closing_speed = closing_speed

    return V8BarnActionCertificate(
        schema_version=evaluated_profile.schema_version,
        certifier_id=evaluated_profile.certifier_id,
        profile_id=evaluated_profile.profile_id,
        profile_sha256=evaluated_profile.identity_sha256,
        boundary_algorithm_id=evaluated_profile.boundary_algorithm_id,
        boundary_scope=BARN_V8_BOUNDARY_SCOPE,
        boundary_rule_scope=BARN_V8_BOUNDARY_RULE_SCOPE,
        uncertified_domains=BARN_V8_UNCERTIFIED_DOMAINS,
        scan_sha256=_scan_sha256(ranges, angle_min, angle_increment),
        action_sha256=_action_sha256(vx, yaw_rate, control_period),
        ray_count=len(ranges),
        examined_ray_count=len(ranges),
        finite_return_count=finite_count,
        clear_ray_count=clear_count,
        unavailable_ray_count=unavailable_count,
        perception_available=finite_count + clear_count > 0,
        perception_complete=unavailable_count == 0,
        positive_closing_return_count=positive_closing_count,
        violating_return_count=violating_count,
        minimum_projected_margin_m=minimum_margin,
        maximum_observed_closing_speed_mps=maximum_closing_speed,
        maximum_swept_projected_displacement_m=(
            evaluated_profile.reaction_horizon_s * maximum_closing_speed
        ),
        limiting_ray_index=limiting_index,
        limiting_range_m=limiting_range,
        limiting_bearing_rad=limiting_bearing,
        limiting_maximum_closing_speed_mps=limiting_closing_speed,
        stop_distance_m=evaluated_profile.stop_distance_m,
        reaction_horizon_s=evaluated_profile.reaction_horizon_s,
        control_period_s=evaluated_profile.control_period_s,
        angle_min_rad=angle_min,
        angle_increment_rad=angle_increment,
        heading_sweep_rad=yaw_rate * evaluated_profile.reaction_horizon_s,
        published_vx_mps=vx,
        published_vy_mps=evaluated_profile.required_lateral_velocity_mps,
        published_yaw_rate_rps=yaw_rate,
        observed_return_boundary_satisfied=violating_count == 0,
    )


__all__ = [
    "BARN_V8_BOUNDARY_ALGORITHM_ID",
    "BARN_V8_BOUNDARY_RULE_SCOPE",
    "BARN_V8_BOUNDARY_SCOPE",
    "BARN_V8_CERTIFIER_ID",
    "BARN_V8_PROFILE_ID",
    "BARN_V8_UNCERTIFIED_DOMAINS",
    "FROZEN_V8_BARN_EVALUATOR_PROFILE",
    "V8BarnActionCertificate",
    "V8BarnEvaluatorProfile",
    "certify_v8_published_barn_action",
]
