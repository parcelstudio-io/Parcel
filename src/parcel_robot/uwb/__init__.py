"""Phase-2 UWB noise model + owner-fusion seam (Sol pure / HR-2).

Sim stand-in for Go2 ``rt/uwbstate``: bearing/range noise, multipath dropouts,
extras injector, and a vision↔UWB primary switch that emits ``OwnerTrackV1``
without contract change. No real UWB hardware.
"""

from __future__ import annotations

from parcel_robot.uwb.fusion import (
    DOES_NOT_PROVE as FUSION_DOES_NOT_PROVE,
)
from parcel_robot.uwb.fusion import (
    OWNER_CHANNEL_PRIMARIES,
    OwnerChannelPrimary,
    OwnerFusionConfig,
    OwnerFusionResult,
    OwnerFusionStub,
)
from parcel_robot.uwb.injector import (
    DOES_NOT_PROVE as INJECTOR_DOES_NOT_PROVE,
)
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

DOES_NOT_PROVE = INJECTOR_DOES_NOT_PROVE + FUSION_DOES_NOT_PROVE

__all__ = [
    "DEFAULT_UWB_TTL_NS",
    "DOES_NOT_PROVE",
    "EXTRAS_KEY",
    "FUSION_DOES_NOT_PROVE",
    "INJECTOR_DOES_NOT_PROVE",
    "OWNER_CHANNEL_PRIMARIES",
    "GroundTruthUwb",
    "MultipathDropoutSchedule",
    "MultipathWindow",
    "OwnerChannelPrimary",
    "OwnerFusionConfig",
    "OwnerFusionResult",
    "OwnerFusionStub",
    "SimUwbInjector",
    "SimUwbPose",
    "UwbNoiseConfig",
    "UwbNoiseModel",
    "UwbSample",
    "bearing_range_from_pose",
    "schedule_from_windows",
    "uwb_from_extras",
]
