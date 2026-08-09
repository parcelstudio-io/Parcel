"""Phase-3 GNSS covariance/dropout model + sim injector (pure / HR-3).

Sim stand-in for ZED-F9P-class ``gnss/fix``: planar east/north noise,
covariance inflation after dropouts, canyon schedule, extras injector.
No real receiver / NTRIP.
"""

from __future__ import annotations

from parcel_robot.gnss.injector import (
    DOES_NOT_PROVE,
    EXTRAS_KEY,
    SimGnssInjector,
    SimGnssPose,
    gnss_from_extras,
)
from parcel_robot.gnss.model import DEFAULT_GNSS_TTL_NS, GnssNoiseModel, GroundTruthGnss
from parcel_robot.gnss.noise import (
    GnssDropoutSchedule,
    GnssDropoutWindow,
    GnssNoiseConfig,
    schedule_from_windows,
)
from parcel_robot.gnss.sample import GnssFix

__all__ = [
    "DEFAULT_GNSS_TTL_NS",
    "DOES_NOT_PROVE",
    "EXTRAS_KEY",
    "GnssDropoutSchedule",
    "GnssDropoutWindow",
    "GnssFix",
    "GnssNoiseConfig",
    "GnssNoiseModel",
    "GroundTruthGnss",
    "SimGnssInjector",
    "SimGnssPose",
    "gnss_from_extras",
    "schedule_from_windows",
]
