"""Phase-3 city-layer maps: OSM footway graph, Overture tiles, crossing policy.

All offline against cached fixtures under ``runtime_assets/maps/``.
No Nav2 authority migration. Fail-closed road geofence.
"""

from __future__ import annotations

# Kept, not a re-export: the ``DOES_NOT_PROVE`` tuple defined below is composed
# from its leaves' own tuples, and `tests/test_p3_city_layer.py` reads it from this package.
from parcel_robot.maps.crossing import DOES_NOT_PROVE as CROSSING_DOES_NOT_PROVE
from parcel_robot.maps.graph import DOES_NOT_PROVE as GRAPH_DOES_NOT_PROVE
from parcel_robot.maps.overture import DOES_NOT_PROVE as OVERTURE_DOES_NOT_PROVE
from parcel_robot.maps.waypoints import DOES_NOT_PROVE as WAYPOINT_DOES_NOT_PROVE

DOES_NOT_PROVE = (
    GRAPH_DOES_NOT_PROVE
    + OVERTURE_DOES_NOT_PROVE
    + CROSSING_DOES_NOT_PROVE
    + WAYPOINT_DOES_NOT_PROVE
)

__all__ = [
    "DOES_NOT_PROVE",
]
