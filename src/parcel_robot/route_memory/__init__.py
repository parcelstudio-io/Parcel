"""Phase-4 route memory + teach-and-repeat + CityWalker / VLFM stubs (sim).

GuideNav-adapted store and gated SE2Goal proposers. Learned outputs never
author velocity. CityWalker / VLFM remain fail-closed / UNVERIFIED until
promotion gates pass. No Nav2. No hardware.
"""

from __future__ import annotations

# Kept, not a re-export: the ``DOES_NOT_PROVE`` tuple defined below is composed
# from its leaves' own tuples, and `tests/test_p4_route_memory.py` reads it from this package.
from parcel_robot.route_memory.citywalker import DOES_NOT_PROVE as CITYWALKER_DOES_NOT_PROVE
from parcel_robot.route_memory.memory import DOES_NOT_PROVE as MEMORY_DOES_NOT_PROVE
from parcel_robot.route_memory.place_graph import DOES_NOT_PROVE as PLACE_GRAPH_DOES_NOT_PROVE
from parcel_robot.route_memory.proposer import DOES_NOT_PROVE as PROPOSER_DOES_NOT_PROVE
from parcel_robot.route_memory.runtime_hook import DOES_NOT_PROVE as HOOK_DOES_NOT_PROVE
from parcel_robot.route_memory.teach_repeat import DOES_NOT_PROVE as TEACH_DOES_NOT_PROVE
from parcel_robot.route_memory.vlfm import DOES_NOT_PROVE as VLFM_DOES_NOT_PROVE
from parcel_robot.route_memory.vpr import DOES_NOT_PROVE as VPR_DOES_NOT_PROVE

DOES_NOT_PROVE = (
    MEMORY_DOES_NOT_PROVE
    + VPR_DOES_NOT_PROVE
    + PROPOSER_DOES_NOT_PROVE
    + TEACH_DOES_NOT_PROVE
    + CITYWALKER_DOES_NOT_PROVE
    + VLFM_DOES_NOT_PROVE
    + HOOK_DOES_NOT_PROVE
    + PLACE_GRAPH_DOES_NOT_PROVE
)

__all__ = [
    "DOES_NOT_PROVE",
]
