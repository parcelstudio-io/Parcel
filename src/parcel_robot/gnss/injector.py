"""Sim injector: attach noisy GNSS to headless extras (pure).

Privileged GT positions may be used *inside* this helper; the agent-facing
output is always ``GnssFix`` / bag-shaped ``gnss`` extras — never oracle
fields on the extras dict.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from parcel_robot.gnss.model import GnssNoiseModel, GroundTruthGnss
from parcel_robot.gnss.noise import GnssNoiseConfig
from parcel_robot.gnss.sample import GnssFix

DOES_NOT_PROVE = (
    (
        "Sim GNSS noise is an HR-3 stand-in for city-layer path tests, not "
        "characterized ZED-F9P / NTRIP / urban-canyon statistics."
    ),
    (
        "Privileged GT pose → noise model is scorer/test-only; agent path consumes "
        "GnssFix / extras['gnss'] only."
    ),
)

EXTRAS_KEY = "gnss"


@dataclass(frozen=True, slots=True)
class SimGnssPose:
    """Minimal robot map pose for the injector (avoids hard backend import)."""

    east_m: float
    north_m: float

    def __post_init__(self) -> None:
        for name, value in (("east_m", self.east_m), ("north_m", self.north_m)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")


class SimGnssInjector:
    """Produce agent-safe GNSS fixes and attach them to observation extras."""

    def __init__(
        self,
        model: GnssNoiseModel | None = None,
        *,
        config: GnssNoiseConfig | None = None,
    ) -> None:
        if model is not None and config is not None:
            raise ValueError("pass model or config, not both")
        self._model = model if model is not None else GnssNoiseModel(config)

    @property
    def model(self) -> GnssNoiseModel:
        return self._model

    def sample_from_pose(
        self,
        pose: SimGnssPose,
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int | None = None,
        scene_revision: int = 0,
    ) -> GnssFix | None:
        if not isinstance(pose, SimGnssPose):
            raise TypeError("pose must be SimGnssPose")
        truth = GroundTruthGnss(east_m=pose.east_m, north_m=pose.north_m)
        return self._model.observe(
            truth,
            rng=rng,
            received_monotonic_ns=received_monotonic_ns,
            source_timestamp_ns=source_timestamp_ns,
            scene_revision=scene_revision,
            evidence_id_prefix="sim-gnss",
        )

    def sample_from_observation(
        self,
        observation: Any,
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int | None = None,
    ) -> GnssFix | None:
        """Lift ``SimObservation`` robot x/y into a GNSS fix (map ≈ odom for sim)."""

        robot = observation.robot
        ts = source_timestamp_ns
        if ts is None:
            raw_ts = getattr(observation, "timestamp", None)
            if isinstance(raw_ts, (int, float)) and math.isfinite(float(raw_ts)):
                ts = int(float(raw_ts) * 1e9)
        return self.sample_from_pose(
            SimGnssPose(east_m=float(robot.x), north_m=float(robot.y)),
            rng=rng,
            received_monotonic_ns=received_monotonic_ns,
            source_timestamp_ns=ts,
        )

    def inject_extras(
        self,
        extras: MutableMapping[str, object],
        sample: GnssFix | None,
        *,
        key: str = EXTRAS_KEY,
    ) -> MutableMapping[str, object]:
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
        key: str = EXTRAS_KEY,
    ) -> GnssFix | None:
        sample = self.sample_from_observation(
            observation,
            rng=rng,
            received_monotonic_ns=received_monotonic_ns,
        )
        self.inject_extras(extras, sample, key=key)
        return sample


def gnss_from_extras(extras: Mapping[str, object], *, key: str = EXTRAS_KEY) -> GnssFix | None:
    """Parse agent extras back into GnssFix; None on missing/dropout."""

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
        "east_m": raw["east_m"],
        "north_m": raw["north_m"],
        "cov_east_m2": raw["cov_east_m2"],
        "cov_north_m2": raw["cov_north_m2"],
        "cov_cross_m2": raw["cov_cross_m2"],
        "hdop": raw["hdop"],
        "num_sats": raw["num_sats"],
        "fix_type": raw["fix_type"],
        "horizontal_std_m": raw["horizontal_std_m"],
    }
    return GnssFix.from_mapping(payload)
