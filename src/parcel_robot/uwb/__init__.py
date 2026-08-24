"""Phase-2 UWB noise model + owner-fusion seam (Sol pure / HR-2).

Sim stand-in for Go2 ``rt/uwbstate``: bearing/range noise, multipath dropouts,
extras injector, and a vision↔UWB primary switch that emits ``OwnerTrackV1``
without contract change. No real UWB hardware.
"""

from __future__ import annotations

# Kept, not a re-export: the ``DOES_NOT_PROVE`` tuple defined below is composed
# from its leaves' own tuples, and `tests/test_p2_uwb_noise.py` reads it from this package.
from parcel_robot.uwb.fusion import DOES_NOT_PROVE as FUSION_DOES_NOT_PROVE
from parcel_robot.uwb.injector import DOES_NOT_PROVE as INJECTOR_DOES_NOT_PROVE

DOES_NOT_PROVE = INJECTOR_DOES_NOT_PROVE + FUSION_DOES_NOT_PROVE

__all__ = [
    "DOES_NOT_PROVE",
]
