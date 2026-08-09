"""OSM footway/crossing graph loaded from a cached neighborhood fixture.

Default path: packaged ``runtime_assets/maps/neighborhood_v1.json``.
Optional ``osmnx`` refresh is offline-fail-closed — CI never requires network.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.paths import packaged_assets_root, resolve_asset

DEFAULT_NEIGHBORHOOD_RELATIVE = "maps/neighborhood_v1.json"
FOOTWAY_HIGHWAYS = frozenset({"footway", "path", "pedestrian", "sidewalk"})
CROSSING_HIGHWAYS = frozenset({"crossing"})
ALLOWED_HIGHWAYS = FOOTWAY_HIGHWAYS | CROSSING_HIGHWAYS

DOES_NOT_PROVE = (
    "Cached OSM fixture does not prove live osmnx topology or surveyed sidewalks.",
    "Local ENU meters are sim-scene coordinates, not WGS84 field localization (HR-10).",
)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    x: float
    y: float
    kind: str = "footway"

    def __post_init__(self) -> None:
        _string(self.id, "id")
        _finite(self.x, "x")
        _finite(self.y, "y")
        _string(self.kind, "kind")


@dataclass(frozen=True, slots=True)
class GraphEdge:
    id: str
    u: str
    v: str
    highway: str
    length_m: float

    def __post_init__(self) -> None:
        _string(self.id, "id")
        _string(self.u, "u")
        _string(self.v, "v")
        highway = _string(self.highway, "highway")
        if highway not in ALLOWED_HIGHWAYS:
            raise ValueError(f"highway {highway!r} not in {sorted(ALLOWED_HIGHWAYS)}")
        length = _finite(self.length_m, "length_m")
        if length <= 0.0:
            raise ValueError("length_m must be positive")

    @property
    def is_crossing(self) -> bool:
        return self.highway in CROSSING_HIGHWAYS


@dataclass(frozen=True, slots=True)
class CurbRecord:
    id: str
    node_id: str
    crossing_edge_ids: tuple[str, ...]
    approach_side: str
    announcement: str

    def __post_init__(self) -> None:
        _string(self.id, "id")
        _string(self.node_id, "node_id")
        if not isinstance(self.crossing_edge_ids, tuple) or not self.crossing_edge_ids:
            raise ValueError("crossing_edge_ids must be a non-empty tuple")
        for edge_id in self.crossing_edge_ids:
            _string(edge_id, "crossing_edge_id")
        _string(self.approach_side, "approach_side")
        _string(self.announcement, "announcement")


@dataclass(frozen=True, slots=True)
class RoadKeepout:
    id: str
    polygon: tuple[tuple[float, float], ...]
    note: str = ""

    def __post_init__(self) -> None:
        _string(self.id, "id")
        if len(self.polygon) < 3:
            raise ValueError("polygon must have at least 3 vertices")
        for x, y in self.polygon:
            _finite(x, "polygon.x")
            _finite(y, "polygon.y")

    def contains(self, x: float, y: float) -> bool:
        """Ray-cast point-in-polygon (inclusive of edge for fail-closed geofence)."""

        px, py = _finite(x, "x"), _finite(y, "y")
        inside = False
        n = len(self.polygon)
        for i in range(n):
            x1, y1 = self.polygon[i]
            x2, y2 = self.polygon[(i + 1) % n]
            if abs((x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)) < 1e-9 and (
                min(x1, x2) - 1e-9 <= px <= max(x1, x2) + 1e-9
                and min(y1, y2) - 1e-9 <= py <= max(y1, y2) + 1e-9
            ):
                return True
            intersects = (y1 > py) != (y2 > py)
            if intersects:
                x_at = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if px < x_at or abs(px - x_at) < 1e-9:
                    inside = not inside
        return inside


@dataclass(frozen=True, slots=True)
class FootwayCrossingGraph:
    """Undirected footway + crossing graph for topological waypoint proposals."""

    fixture_id: str
    nodes: Mapping[str, GraphNode]
    edges: Mapping[str, GraphEdge]
    curbs: Mapping[str, CurbRecord]
    road_keepout: RoadKeepout | None
    does_not_prove: tuple[str, ...] = DOES_NOT_PROVE

    def __post_init__(self) -> None:
        _string(self.fixture_id, "fixture_id")
        if not self.nodes:
            raise ValueError("nodes must be non-empty")
        if not self.edges:
            raise ValueError("edges must be non-empty")
        for edge in self.edges.values():
            if edge.u not in self.nodes or edge.v not in self.nodes:
                raise ValueError(f"edge {edge.id} references unknown node")
        for curb in self.curbs.values():
            if curb.node_id not in self.nodes:
                raise ValueError(f"curb {curb.id} references unknown node")
            for edge_id in curb.crossing_edge_ids:
                if edge_id not in self.edges:
                    raise ValueError(f"curb {curb.id} references unknown edge {edge_id}")
                if not self.edges[edge_id].is_crossing:
                    raise ValueError(f"curb edge {edge_id} must be highway=crossing")

    def adjacency(self) -> dict[str, list[tuple[str, GraphEdge]]]:
        adj: dict[str, list[tuple[str, GraphEdge]]] = defaultdict(list)
        for edge in self.edges.values():
            adj[edge.u].append((edge.v, edge))
            adj[edge.v].append((edge.u, edge))
        return dict(adj)

    def nearest_node(self, x: float, y: float, *, kinds: Iterable[str] | None = None) -> GraphNode:
        allowed = None if kinds is None else frozenset(kinds)
        best: GraphNode | None = None
        best_d = float("inf")
        for node in self.nodes.values():
            if allowed is not None and node.kind not in allowed:
                continue
            d = math.hypot(node.x - x, node.y - y)
            if d < best_d:
                best_d = d
                best = node
        if best is None:
            raise ValueError("no node matches kinds filter")
        return best

    def shortest_path(
        self,
        start_id: str,
        goal_id: str,
        *,
        allow_crossing: bool = False,
    ) -> tuple[GraphNode, ...] | None:
        """BFS shortest hop path. Crossing edges require ``allow_crossing``."""

        if start_id not in self.nodes or goal_id not in self.nodes:
            raise ValueError("start_id and goal_id must be graph nodes")
        if start_id == goal_id:
            return (self.nodes[start_id],)

        adj = self.adjacency()
        prev: dict[str, str | None] = {start_id: None}
        queue: deque[str] = deque([start_id])
        while queue:
            current = queue.popleft()
            for neighbor, edge in adj.get(current, []):
                if edge.is_crossing and not allow_crossing:
                    continue
                if neighbor in prev:
                    continue
                prev[neighbor] = current
                if neighbor == goal_id:
                    path_ids: list[str] = [goal_id]
                    cursor: str | None = goal_id
                    while cursor is not None and cursor != start_id:
                        cursor = prev[cursor]
                        if cursor is None:
                            break
                        path_ids.append(cursor)
                    path_ids.reverse()
                    return tuple(self.nodes[nid] for nid in path_ids)
                queue.append(neighbor)
        return None

    def path_waypoints(
        self,
        start_xy: tuple[float, float],
        goal_xy: tuple[float, float],
        *,
        allow_crossing: bool = False,
    ) -> tuple[tuple[float, float], ...] | None:
        start = self.nearest_node(start_xy[0], start_xy[1])
        goal = self.nearest_node(goal_xy[0], goal_xy[1])
        path = self.shortest_path(start.id, goal.id, allow_crossing=allow_crossing)
        if path is None:
            return None
        return tuple((n.x, n.y) for n in path)

    def curb_at_node(self, node_id: str) -> CurbRecord | None:
        for curb in self.curbs.values():
            if curb.node_id == node_id:
                return curb
        return None

    def crossing_edge_ids(self) -> frozenset[str]:
        return frozenset(e.id for e in self.edges.values() if e.is_crossing)

    def is_road_keepout(self, x: float, y: float) -> bool:
        if self.road_keepout is None:
            return False
        return self.road_keepout.contains(x, y)


def resolve_neighborhood_fixture(path: str | Path | None = None) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(f"neighborhood fixture missing: {candidate}")
    try:
        return resolve_asset(*Path(DEFAULT_NEIGHBORHOOD_RELATIVE).parts, kind="file")
    except FileNotFoundError:
        fallback = packaged_assets_root() / DEFAULT_NEIGHBORHOOD_RELATIVE
        if fallback.is_file():
            return fallback.resolve()
        raise


def load_footway_crossing_graph(path: str | Path | None = None) -> FootwayCrossingGraph:
    """Load the cached neighborhood fixture (default packaged asset)."""

    fixture_path = resolve_neighborhood_fixture(path)
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    return graph_from_mapping(raw)


def graph_from_mapping(raw: Mapping[str, Any]) -> FootwayCrossingGraph:
    if not isinstance(raw, Mapping):
        raise TypeError("fixture must be a mapping")
    nodes = {
        str(item["id"]): GraphNode(
            id=str(item["id"]),
            x=float(item["x"]),
            y=float(item["y"]),
            kind=str(item.get("kind", "footway")),
        )
        for item in raw["nodes"]
    }
    edges = {
        str(item["id"]): GraphEdge(
            id=str(item["id"]),
            u=str(item["u"]),
            v=str(item["v"]),
            highway=str(item["highway"]),
            length_m=float(item["length_m"]),
        )
        for item in raw["edges"]
    }
    curbs = {
        str(item["id"]): CurbRecord(
            id=str(item["id"]),
            node_id=str(item["node_id"]),
            crossing_edge_ids=tuple(str(e) for e in item["crossing_edge_ids"]),
            approach_side=str(item["approach_side"]),
            announcement=str(item["announcement"]),
        )
        for item in raw.get("curbs", [])
    }
    keepout_raw = raw.get("road_keepout")
    keepout = None
    if keepout_raw is not None:
        keepout = RoadKeepout(
            id=str(keepout_raw["id"]),
            polygon=tuple((float(p[0]), float(p[1])) for p in keepout_raw["polygon"]),
            note=str(keepout_raw.get("note", "")),
        )
    dnp = tuple(str(s) for s in raw.get("does_not_prove", DOES_NOT_PROVE))
    return FootwayCrossingGraph(
        fixture_id=str(raw.get("fixture_id", "unknown")),
        nodes=nodes,
        edges=edges,
        curbs=curbs,
        road_keepout=keepout,
        does_not_prove=dnp,
    )


def try_osmnx_pull_to_fixture(
    *,
    place_query: str,
    out_path: str | Path,
    dist_m: float = 250.0,
) -> Path:
    """Optional osmnx refresh. Fail-closed if osmnx/network unavailable.

    CI and default runtime never call this — they load the shipped fixture.
    """

    try:
        import osmnx as ox  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "osmnx is not installed; use the shipped neighborhood fixture"
        ) from exc

    # Keep the network call behind an explicit helper so default imports stay offline.
    graph = ox.graph_from_address(place_query, dist=dist_m, network_type="walk")
    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    for node_id, data in graph.nodes(data=True):
        nodes_out.append(
            {
                "id": f"n_{node_id}",
                "x": float(data.get("x", 0.0)),
                "y": float(data.get("y", 0.0)),
                "kind": "footway",
            }
        )
    for u, v, key, data in graph.edges(keys=True, data=True):
        highway = data.get("highway", "footway")
        if isinstance(highway, list):
            highway = highway[0] if highway else "footway"
        highway_s = str(highway)
        if highway_s not in ALLOWED_HIGHWAYS:
            # Keep only pedestrian-class edges in the city-layer fixture.
            if highway_s not in {"residential", "service", "living_street"}:
                continue
            highway_s = "footway"
        length = float(data.get("length", 1.0))
        edges_out.append(
            {
                "id": f"e_{u}_{v}_{key}",
                "u": f"n_{u}",
                "v": f"n_{v}",
                "highway": highway_s if highway_s in ALLOWED_HIGHWAYS else "footway",
                "length_m": max(length, 0.1),
            }
        )
    payload = {
        "schema_version": 1,
        "fixture_id": f"osmnx-{place_query.replace(' ', '-').lower()}",
        "source": "osmnx_pull",
        "crs": "local_projected",
        "does_not_prove": list(DOES_NOT_PROVE),
        "nodes": nodes_out,
        "edges": edges_out,
        "curbs": [],
        "road_keepout": None,
        "place_query": place_query,
        "dist_m": dist_m,
    }
    destination = Path(out_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination.resolve()
