"""GuideNav-adapted route memory store (sim teach-and-repeat substrate).

Records a sequence of keyframes (SE2 pose + optional VPR embedding stub) from
a sim walk. Replay emits SE2Goal proposals only — never model-authored
velocity. Learned proposers remain behind an explicit gate.

**RM-1 amendment (2026-08-12, scrum/20260811/task_2/SLAM_M_PLAN.md card RM-1).**
:class:`RouteKeyframe` gained three additive, defaulted fields —
``frame``, ``labels``, ``tick`` — so the queryable place graph
(:mod:`parcel_robot.route_memory.place_graph`) can build on the store's
existing keyframe type instead of forking a parallel one.  All three carry
behaviour-preserving defaults and are appended *after* the pre-existing fields,
so positional construction (``RouteKeyframe(0.0, 0.0, 0.0)``) and every v1
payload on disk are unchanged: ``from_mapping`` supplies the same defaults for
a payload that lacks the keys, and a v1 reader ignores keys it does not know.
``ROUTE_MEMORY_SCHEMA`` therefore stays at ``v1`` — the change is additive in
both directions, not a format break.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROUTE_MEMORY_SCHEMA = "parcel.route_memory.v1"
PROPOSER_SOURCE = "route_memory_v1"

DOES_NOT_PROVE = (
    (
        "Route memory is a sim teach-and-repeat store over rendered frames / "
        "pose stubs; it does not prove GuideNav CosPlace+Reloc3r field "
        "performance, Orin NX 5 Hz budget, or km-scale route success (HR-12)."
    ),
)


@dataclass(frozen=True, slots=True)
class RouteKeyframe:
    """One teach keyframe: map-frame SE2 pose + optional embedding stub.

    ``frame_id`` and ``frame`` are different channels and the names are
    unfortunately close:

    ``frame_id``
        the *rendered image* identifier this keyframe's embedding came from
        (pairs with ``frame_bytes`` on the VPR seam).  Pre-existing.

    ``frame``
        the REP-105 **coordinate** frame the pose is expressed in, mirroring
        :attr:`RoutePath.frame`.  RM-1 amendment: the place graph only ever
        ingests ``parcel_robot.pose.Frame.MAP`` poses, and recording the frame
        on the keyframe itself (not just on the enclosing path) is what makes a
        persisted keyframe self-describing — a loader can refuse an ``odom``
        keyframe without trusting its container.

    ``labels`` are the resolved semantic labels observed at this place and
    ``tick`` is the ingestion-time monotonic tick counter, both RM-1 additions
    for :meth:`~parcel_robot.route_memory.place_graph.RoutePlaceGraph.record_visit`.
    """

    x: float
    y: float
    yaw_rad: float
    t_s: float = 0.0
    embedding: tuple[float, ...] = ()
    frame_id: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)
    # RM-1 additive fields — appended last so positional construction of the
    # pre-existing signature keeps working.
    frame: str = "map"
    labels: tuple[str, ...] = ()
    tick: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("yaw_rad", self.yaw_rad),
            ("t_s", self.t_s),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not isinstance(self.embedding, tuple):
            raise TypeError("embedding must be a tuple")
        if len(self.embedding) > 2048:
            raise ValueError("embedding exceeds 2048 dims")
        for item in self.embedding:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise TypeError("embedding components must be numeric")
            if not math.isfinite(float(item)):
                raise ValueError("embedding components must be finite")
        if not isinstance(self.frame_id, str):
            raise TypeError("frame_id must be a string")
        if not isinstance(self.meta, Mapping):
            raise TypeError("meta must be a mapping")
        # --- RM-1 additive fields ---
        if not isinstance(self.frame, str) or not self.frame.strip():
            raise ValueError("frame must be a non-empty string")
        if not isinstance(self.labels, tuple):
            raise TypeError("labels must be a tuple")
        for label in self.labels:
            if not isinstance(label, str):
                raise TypeError("labels must contain strings")
        if isinstance(self.tick, bool) or not isinstance(self.tick, int):
            raise TypeError("tick must be an int")
        if self.tick < 0:
            raise ValueError("tick must be non-negative")

    @property
    def pose(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.yaw_rad))

    @property
    def xy(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))

    def as_dict(self) -> dict[str, Any]:
        return {
            "x": float(self.x),
            "y": float(self.y),
            "yaw_rad": float(self.yaw_rad),
            "t_s": float(self.t_s),
            "embedding": [float(v) for v in self.embedding],
            "frame_id": self.frame_id,
            "meta": dict(self.meta),
            # RM-1: frame discipline is persisted per keyframe, not inferred.
            "frame": self.frame,
            "labels": list(self.labels),
            "tick": int(self.tick),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RouteKeyframe:
        if not isinstance(data, Mapping):
            raise TypeError("RouteKeyframe data must be a mapping")
        emb_raw = data.get("embedding", ())
        if emb_raw is None:
            emb_raw = ()
        if not isinstance(emb_raw, Sequence) or isinstance(emb_raw, (str, bytes)):
            raise TypeError("embedding must be a sequence of floats")
        meta = data.get("meta", {})
        if meta is None:
            meta = {}
        if not isinstance(meta, Mapping):
            raise TypeError("meta must be a mapping")
        # RM-1: absent keys take the pre-amendment defaults, so v1 payloads
        # written before this change still load byte-for-byte identically.
        labels_raw = data.get("labels", ())
        if labels_raw is None:
            labels_raw = ()
        if not isinstance(labels_raw, Sequence) or isinstance(labels_raw, (str, bytes)):
            raise TypeError("labels must be a sequence of strings")
        return cls(
            x=float(data["x"]),
            y=float(data["y"]),
            yaw_rad=float(data["yaw_rad"]),
            t_s=float(data.get("t_s", 0.0)),
            embedding=tuple(float(v) for v in emb_raw),
            frame_id=str(data.get("frame_id", "")),
            meta=dict(meta),
            frame=str(data.get("frame", "map")),
            labels=tuple(str(s) for s in labels_raw),
            tick=int(data.get("tick", 0)),
        )


@dataclass(frozen=True, slots=True)
class RoutePath:
    """Named taught path: ordered keyframes + provenance."""

    path_id: str
    keyframes: tuple[RouteKeyframe, ...]
    name: str = ""
    frame: str = "map"
    created_s: float = 0.0
    does_not_prove: tuple[str, ...] = DOES_NOT_PROVE
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.path_id, str) or not self.path_id.strip():
            raise ValueError("path_id must be non-empty")
        if not isinstance(self.keyframes, tuple):
            raise TypeError("keyframes must be a tuple")
        if not self.keyframes:
            raise ValueError("keyframes must be non-empty")
        for kf in self.keyframes:
            if not isinstance(kf, RouteKeyframe):
                raise TypeError("keyframes must contain RouteKeyframe")
        if not isinstance(self.name, str):
            raise TypeError("name must be a string")
        if not isinstance(self.frame, str) or not self.frame.strip():
            raise ValueError("frame must be non-empty")
        if isinstance(self.created_s, bool) or not isinstance(self.created_s, (int, float)):
            raise TypeError("created_s must be numeric")
        if not math.isfinite(float(self.created_s)):
            raise ValueError("created_s must be finite")
        if not isinstance(self.does_not_prove, tuple) or not self.does_not_prove:
            raise ValueError("does_not_prove must be a non-empty tuple of strings")
        if not isinstance(self.meta, Mapping):
            raise TypeError("meta must be a mapping")

    def waypoints_xy(self) -> tuple[tuple[float, float], ...]:
        return tuple((kf.x, kf.y) for kf in self.keyframes)

    def terminal_pose(self) -> tuple[float, float, float]:
        last = self.keyframes[-1]
        return last.pose

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ROUTE_MEMORY_SCHEMA,
            "path_id": self.path_id,
            "name": self.name,
            "frame": self.frame,
            "created_s": float(self.created_s),
            "keyframes": [kf.as_dict() for kf in self.keyframes],
            "does_not_prove": list(self.does_not_prove),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RoutePath:
        if not isinstance(data, Mapping):
            raise TypeError("RoutePath data must be a mapping")
        schema = data.get("schema_version", ROUTE_MEMORY_SCHEMA)
        if schema != ROUTE_MEMORY_SCHEMA:
            raise ValueError(f"unsupported route memory schema: {schema!r}")
        raw_kfs = data.get("keyframes")
        if not isinstance(raw_kfs, Sequence) or isinstance(raw_kfs, (str, bytes)):
            raise TypeError("keyframes must be a sequence")
        dnp = data.get("does_not_prove", DOES_NOT_PROVE)
        if not isinstance(dnp, Sequence) or isinstance(dnp, (str, bytes)):
            raise TypeError("does_not_prove must be a sequence of strings")
        meta = data.get("meta", {})
        if meta is None:
            meta = {}
        if not isinstance(meta, Mapping):
            raise TypeError("meta must be a mapping")
        return cls(
            path_id=str(data["path_id"]),
            name=str(data.get("name", "")),
            frame=str(data.get("frame", "map")),
            created_s=float(data.get("created_s", 0.0)),
            keyframes=tuple(RouteKeyframe.from_mapping(item) for item in raw_kfs),
            does_not_prove=tuple(str(s) for s in dnp),
            meta=dict(meta),
        )


class RouteMemoryStore:
    """In-memory + optional on-disk store for taught routes."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = Path(root).expanduser().resolve() if root is not None else None
        self._paths: dict[str, RoutePath] = {}

    @property
    def root(self) -> Path | None:
        return self._root

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._paths))

    def get(self, path_id: str) -> RoutePath | None:
        return self._paths.get(path_id)

    def require(self, path_id: str) -> RoutePath:
        path = self.get(path_id)
        if path is None:
            raise KeyError(f"unknown route path_id: {path_id!r}")
        return path

    def put(self, path: RoutePath) -> RoutePath:
        if not isinstance(path, RoutePath):
            raise TypeError("path must be RoutePath")
        self._paths[path.path_id] = path
        return path

    def record(
        self,
        keyframes: Sequence[RouteKeyframe],
        *,
        path_id: str | None = None,
        name: str = "",
        frame: str = "map",
        created_s: float = 0.0,
        meta: Mapping[str, Any] | None = None,
    ) -> RoutePath:
        """Create and store a RoutePath from a sim-walk keyframe sequence."""

        if not isinstance(keyframes, Sequence) or isinstance(keyframes, (str, bytes)):
            raise TypeError("keyframes must be a sequence")
        pid = (path_id or f"route-{uuid.uuid4().hex[:12]}").strip()
        path = RoutePath(
            path_id=pid,
            keyframes=tuple(keyframes),
            name=name,
            frame=frame,
            created_s=float(created_s),
            meta=dict(meta or {}),
        )
        return self.put(path)

    def save(self, path_id: str, *, directory: Path | None = None) -> Path:
        path = self.require(path_id)
        out_dir = directory if directory is not None else self._root
        if out_dir is None:
            raise ValueError("no store root or directory given for save")
        out_dir = Path(out_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{path.path_id}.json"
        target.write_text(json.dumps(path.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target

    def load(self, file_path: Path | str) -> RoutePath:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"route memory file missing: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise TypeError("route memory JSON must be an object")
        route = RoutePath.from_mapping(data)
        return self.put(route)

    def load_all(self, directory: Path | None = None) -> tuple[RoutePath, ...]:
        out_dir = directory if directory is not None else self._root
        if out_dir is None:
            raise ValueError("no store root or directory given for load_all")
        out_dir = Path(out_dir).expanduser().resolve()
        if not out_dir.is_dir():
            raise FileNotFoundError(f"route memory directory missing: {out_dir}")
        loaded: list[RoutePath] = []
        for file_path in sorted(out_dir.glob("*.json")):
            loaded.append(self.load(file_path))
        return tuple(loaded)
