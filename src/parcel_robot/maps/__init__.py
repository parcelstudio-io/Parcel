"""Phase-3 city-layer maps: OSM footway graph, Overture tiles, crossing policy.

All offline against cached fixtures under ``runtime_assets/maps/``.
No Nav2 authority migration. Fail-closed road geofence.
"""

from __future__ import annotations

from parcel_robot.maps.crossing import (
    DOES_NOT_PROVE as CROSSING_DOES_NOT_PROVE,
)
from parcel_robot.maps.crossing import (
    VOICE_CROSS_PHRASES,
    CrossingDecision,
    CrossingModePolicy,
    CrossingPolicyConfig,
    CrossingState,
    decision_blocks_autonomous_road,
    summarize_policy,
)
from parcel_robot.maps.graph import (
    ALLOWED_HIGHWAYS,
    CROSSING_HIGHWAYS,
    DEFAULT_NEIGHBORHOOD_RELATIVE,
    FOOTWAY_HIGHWAYS,
    CurbRecord,
    FootwayCrossingGraph,
    GraphEdge,
    GraphNode,
    RoadKeepout,
    graph_from_mapping,
    load_footway_crossing_graph,
    resolve_neighborhood_fixture,
    try_osmnx_pull_to_fixture,
)
from parcel_robot.maps.graph import (
    DOES_NOT_PROVE as GRAPH_DOES_NOT_PROVE,
)
from parcel_robot.maps.overture import (
    DEFAULT_OVERTURE_RELATIVE,
    OverturePlace,
    OvertureTile,
    OvertureTileClient,
    load_overture_tile,
    resolve_overture_fixture,
    tile_from_mapping,
)
from parcel_robot.maps.overture import (
    DOES_NOT_PROVE as OVERTURE_DOES_NOT_PROVE,
)
from parcel_robot.maps.waypoints import (
    DOES_NOT_PROVE as WAYPOINT_DOES_NOT_PROVE,
)
from parcel_robot.maps.waypoints import (
    PROPOSER_SOURCE,
    OsmWaypointProposer,
)

DOES_NOT_PROVE = (
    GRAPH_DOES_NOT_PROVE
    + OVERTURE_DOES_NOT_PROVE
    + CROSSING_DOES_NOT_PROVE
    + WAYPOINT_DOES_NOT_PROVE
)

__all__ = [
    "ALLOWED_HIGHWAYS",
    "CROSSING_DOES_NOT_PROVE",
    "CROSSING_HIGHWAYS",
    "DEFAULT_NEIGHBORHOOD_RELATIVE",
    "DEFAULT_OVERTURE_RELATIVE",
    "DOES_NOT_PROVE",
    "FOOTWAY_HIGHWAYS",
    "GRAPH_DOES_NOT_PROVE",
    "OVERTURE_DOES_NOT_PROVE",
    "PROPOSER_SOURCE",
    "VOICE_CROSS_PHRASES",
    "WAYPOINT_DOES_NOT_PROVE",
    "CrossingDecision",
    "CrossingModePolicy",
    "CrossingPolicyConfig",
    "CrossingState",
    "CurbRecord",
    "FootwayCrossingGraph",
    "GraphEdge",
    "GraphNode",
    "OsmWaypointProposer",
    "OverturePlace",
    "OvertureTile",
    "OvertureTileClient",
    "RoadKeepout",
    "decision_blocks_autonomous_road",
    "graph_from_mapping",
    "load_footway_crossing_graph",
    "load_overture_tile",
    "resolve_neighborhood_fixture",
    "resolve_overture_fixture",
    "summarize_policy",
    "tile_from_mapping",
    "try_osmnx_pull_to_fixture",
]
