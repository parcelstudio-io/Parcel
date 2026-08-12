"""Phase-4 route memory + teach-and-repeat + CityWalker / VLFM stubs (sim).

GuideNav-adapted store and gated SE2Goal proposers. Learned outputs never
author velocity. CityWalker / VLFM remain fail-closed / UNVERIFIED until
promotion gates pass. No Nav2. No hardware.
"""

from __future__ import annotations

from parcel_robot.route_memory.citywalker import (
    DOES_NOT_PROVE as CITYWALKER_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.citywalker import (
    PROPOSER_SOURCE as CITYWALKER_PROPOSER_SOURCE,
)
from parcel_robot.route_memory.citywalker import (
    CityWalkerAdapterConfig,
    CityWalkerInferenceAdapter,
    CityWalkerObservation,
    CityWalkerResult,
    load_cached_walk,
    resolve_citywalker_checkpoint,
    resolve_citywalker_vendor,
)
from parcel_robot.route_memory.memory import (
    DOES_NOT_PROVE as MEMORY_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.memory import (
    PROPOSER_SOURCE,
    ROUTE_MEMORY_SCHEMA,
    RouteKeyframe,
    RouteMemoryStore,
    RoutePath,
)
from parcel_robot.route_memory.place_graph import (
    DEFAULT_ATTACH_RADIUS_M,
    DEFAULT_KEYFRAME_SPACING_M,
    DEFAULT_MAX_CONTIGUOUS_STEP_M,
    PLACE_GRAPH_SCHEMA,
    PlaceEdge,
    RoutePlaceGraph,
    stub_embed_image,
)
from parcel_robot.route_memory.place_graph import (
    DOES_NOT_PROVE as PLACE_GRAPH_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.proposer import (
    DEFAULT_WAYPOINT_REACHED_M,
    PLACE_ROUTE_SOURCE,
    RouteMemoryProposer,
    chain_length_m,
    goal_from_path_snapshot,
    next_waypoint_keyframe,
    propose_with_context,
    waypoint_goal_from_chain,
)
from parcel_robot.route_memory.proposer import (
    DOES_NOT_PROVE as PROPOSER_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.runtime_hook import (
    DOES_NOT_PROVE as HOOK_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.runtime_hook import (
    EXTRAS_KEY,
    PLACE_EXTRAS_KEY,
    RouteMemoryPlaceHook,
    RouteMemoryRuntimeHook,
    provider_reanchor_count,
)
from parcel_robot.route_memory.teach_repeat import (
    DOES_NOT_PROVE as TEACH_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.teach_repeat import TeachRepeatSession
from parcel_robot.route_memory.vlfm import (
    DOES_NOT_PROVE as VLFM_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.vlfm import (
    HeuristicValueMap,
    HeuristicVLFMScorer,
    ValueMapCell,
)
from parcel_robot.route_memory.vpr import (
    DOES_NOT_PROVE as VPR_DOES_NOT_PROVE,
)
from parcel_robot.route_memory.vpr import (
    StubVPREmbedder,
    VPREmbedder,
    cosine_similarity,
    match_keyframe_index,
)

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
    "CITYWALKER_DOES_NOT_PROVE",
    "CITYWALKER_PROPOSER_SOURCE",
    "DEFAULT_ATTACH_RADIUS_M",
    "DEFAULT_KEYFRAME_SPACING_M",
    "DEFAULT_MAX_CONTIGUOUS_STEP_M",
    "DEFAULT_WAYPOINT_REACHED_M",
    "DOES_NOT_PROVE",
    "EXTRAS_KEY",
    "HOOK_DOES_NOT_PROVE",
    "MEMORY_DOES_NOT_PROVE",
    "PLACE_EXTRAS_KEY",
    "PLACE_GRAPH_DOES_NOT_PROVE",
    "PLACE_GRAPH_SCHEMA",
    "PLACE_ROUTE_SOURCE",
    "PROPOSER_DOES_NOT_PROVE",
    "PROPOSER_SOURCE",
    "ROUTE_MEMORY_SCHEMA",
    "TEACH_DOES_NOT_PROVE",
    "VLFM_DOES_NOT_PROVE",
    "VPR_DOES_NOT_PROVE",
    "CityWalkerAdapterConfig",
    "CityWalkerInferenceAdapter",
    "CityWalkerObservation",
    "CityWalkerResult",
    "HeuristicVLFMScorer",
    "HeuristicValueMap",
    "PlaceEdge",
    "RouteKeyframe",
    "RouteMemoryPlaceHook",
    "RouteMemoryProposer",
    "RouteMemoryRuntimeHook",
    "RouteMemoryStore",
    "RoutePath",
    "RoutePlaceGraph",
    "StubVPREmbedder",
    "TeachRepeatSession",
    "VPREmbedder",
    "ValueMapCell",
    "chain_length_m",
    "cosine_similarity",
    "goal_from_path_snapshot",
    "load_cached_walk",
    "match_keyframe_index",
    "next_waypoint_keyframe",
    "propose_with_context",
    "provider_reanchor_count",
    "resolve_citywalker_checkpoint",
    "resolve_citywalker_vendor",
    "stub_embed_image",
    "waypoint_goal_from_chain",
]
