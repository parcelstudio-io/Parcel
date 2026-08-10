"""Sim injector: attach noisy UWB to headless / owner-track extras (pure).

Privileged GT positions may be used *inside* this helper; the agent-facing
output is always ``UwbSample`` / bag-shaped ``uwb`` extras — never oracle
fields on the extras dict.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from parcel_robot.uwb.model import GroundTruthUwb, UwbNoiseModel
from parcel_robot.uwb.noise import UwbNoiseConfig
from parcel_robot.uwb.sample import UwbSample

DOES_NOT_PROVE = (
    ("Sim UWB noise is an HR-2 stand-in for owner-fusion path tests, not "
    "characterized rt/uwbstate statistics (indoor/outdoor/occlusion/multipath)."),
    ("Privileged GT pose → noise model is scorer/test-only; agent path consumes "
    "UwbSample / extras['uwb'] only."),
)

EXTRAS_KEY = "uwb"


def bearing_range_from_pose(
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    target_x: float,
    target_y: float,
) -> tuple[float, float]:
    """Body-relative bearing ([-π, π]) and planar range — shared with detection."""

    dx = float(target_x) - float(robot_x)
    dy = float(target_y) - float(robot_y)
    range_m = math.hypot(dx, dy)
    world_bearing = math.atan2(dy, dx)
    bearing = (world_bearing - float(robot_yaw_rad) + math.pi) % (2.0 * math.pi) - math.pi
    return bearing, range_m


@dataclass(frozen=True, slots=True)
class SimUwbPose:
    """Minimal robot/owner pose for the injector (avoids hard backend import)."""

    robot_x: float
    robot_y: float
    robot_yaw_rad: float
    owner_x: float
    owner_y: float
    fob_id: str = "owner-fob-1"

    def __post_init__(self) -> None:
        for name, value in (
            ("robot_x", self.robot_x),
            ("robot_y", self.robot_y),
            ("robot_yaw_rad", self.robot_yaw_rad),
            ("owner_x", self.owner_x),
            ("owner_y", self.owner_y),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not isinstance(self.fob_id, str) or not self.fob_id:
            raise ValueError("fob_id must be non-empty")


class SimUwbInjector:
    """Produce agent-safe UWB samples and attach them to observation extras."""

    def __init__(
        self,
        model: UwbNoiseModel | None = None,
        *,
        config: UwbNoiseConfig | None = None,
    ) -> None:
        if model is not None and config is not None:
            raise ValueError("pass model or config, not both")
        self._model = model if model is not None else UwbNoiseModel(config)

    @property
    def model(self) -> UwbNoiseModel:
        return self._model

    def sample_from_pose(
        self,
        pose: SimUwbPose,
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int | None = None,
        scene_revision: int = 0,
    ) -> UwbSample | None:
        """GT owner pose → noisy UwbSample (None on multipath dropout / cutoff)."""

        if not isinstance(pose, SimUwbPose):
            raise TypeError("pose must be SimUwbPose")
        bearing, range_m = bearing_range_from_pose(
            robot_x=pose.robot_x,
            robot_y=pose.robot_y,
            robot_yaw_rad=pose.robot_yaw_rad,
            target_x=pose.owner_x,
            target_y=pose.owner_y,
        )
        truth = GroundTruthUwb(
            fob_id=pose.fob_id,
            bearing_rad=bearing,
            range_m=range_m,
        )
        return self._model.observe(
            truth,
            rng=rng,
            received_monotonic_ns=received_monotonic_ns,
            source_timestamp_ns=source_timestamp_ns,
            scene_revision=scene_revision,
            evidence_id_prefix="sim-uwb",
        )

    def sample_from_observation(
        self,
        observation: Any,
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        fob_id: str | None = None,
        require_owner_visible: bool = False,
        source_timestamp_ns: int | None = None,
    ) -> UwbSample | None:
        """Lift ``SimObservation`` robot + owner into a UWB sample.

        UWB does not require camera visibility (fob RF). When
        ``require_owner_visible`` is True, invisible owners yield None
        (test convenience only).
        """

        robot = observation.robot
        owner = observation.owner
        if require_owner_visible and not bool(getattr(owner, "visible", True)):
            return None
        resolved_fob = fob_id or str(getattr(owner, "owner_id", "owner-fob-1"))
        ts = source_timestamp_ns
        if ts is None:
            raw_ts = getattr(observation, "timestamp", None)
            if isinstance(raw_ts, (int, float)) and math.isfinite(float(raw_ts)):
                ts = int(float(raw_ts) * 1e9)
        return self.sample_from_pose(
            SimUwbPose(
                robot_x=float(robot.x),
                robot_y=float(robot.y),
                robot_yaw_rad=float(robot.yaw),
                owner_x=float(owner.x),
                owner_y=float(owner.y),
                fob_id=resolved_fob,
            ),
            rng=rng,
            received_monotonic_ns=received_monotonic_ns,
            source_timestamp_ns=ts,
        )

    def inject_extras(
        self,
        extras: MutableMapping[str, object],
        sample: UwbSample | None,
        *,
        key: str = EXTRAS_KEY,
    ) -> MutableMapping[str, object]:
        """Attach bag-shaped UWB payload (or mark dropout) under extras[key]."""

        if not isinstance(extras, MutableMapping):
            raise TypeError("extras must be a mutable mapping")
        if sample is None:
            extras[key] = {"dropout": True, "schema_version": 1}
        else:
            extras[key] = {
                **sample.bag_payload(),
                "envelope": sample.envelope.as_dict(),
                "dropout": False,
            }
        return extras

    def observe_and_inject(
        self,
        observation: Any,
        extras: MutableMapping[str, object],
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        fob_id: str | None = None,
        key: str = EXTRAS_KEY,
    ) -> UwbSample | None:
        """One-shot: sample from observation and write into extras."""

        sample = self.sample_from_observation(
            observation,
            rng=rng,
            received_monotonic_ns=received_monotonic_ns,
            fob_id=fob_id,
        )
        self.inject_extras(extras, sample, key=key)
        return sample


def uwb_from_extras(extras: Mapping[str, object], *, key: str = EXTRAS_KEY) -> UwbSample | None:
    """Parse agent extras back into UwbSample; None on missing/dropout."""

    raw = extras.get(key)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError(f"extras[{key!r}] must be a mapping")
    if raw.get("dropout") is True:
        return None
    if "envelope" not in raw:
        raise ValueError(f"extras[{key!r}] missing envelope for non-dropout sample")
    payload = {
        "envelope": raw["envelope"],
        "fob_id": raw["fob_id"],
        "bearing_rad": raw["bearing_rad"],
        "range_m": raw["range_m"],
        "quality": raw["quality"],
        "multipath_suspect": bool(raw.get("multipath_suspect", False)),
    }
    return UwbSample.from_mapping(payload)
