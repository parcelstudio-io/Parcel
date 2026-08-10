"""Teach-and-repeat API: teach(path) / follow(path_id) — pure + gated.

GuideNav-adapted pattern for Parcel: record keyframes during a sim walk,
then replay as SE2Goal proposals into GoalArbiter. No model-authored
velocity. No Nav2. No hardware.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.route_memory.memory import RouteKeyframe, RouteMemoryStore, RoutePath
from parcel_robot.route_memory.proposer import RouteMemoryProposer
from parcel_robot.route_memory.vpr import StubVPREmbedder, VPREmbedder

DOES_NOT_PROVE = (
    (
        "TeachRepeatSession is a pure sim API over RouteMemoryStore + gated "
        "SE2Goal proposers; it does not prove GuideNav Reloc3r pose regression, "
        "5 Hz Orin NX budgets, or outdoor repeat-route ≥90% (HR-12)."
    ),
)


def _as_keyframe(
    item: RouteKeyframe | Mapping[str, Any] | Sequence[float],
    *,
    t_s: float,
    embedder: VPREmbedder | None,
    frame_bytes: bytes | None = None,
    frame_id: str = "",
) -> RouteKeyframe:
    if isinstance(item, RouteKeyframe):
        kf = item
        if embedder is not None and not kf.embedding:
            emb = embedder.embed(pose=kf.pose, frame_bytes=frame_bytes, frame_id=frame_id or kf.frame_id)
            return RouteKeyframe(
                x=kf.x,
                y=kf.y,
                yaw_rad=kf.yaw_rad,
                t_s=kf.t_s if kf.t_s else t_s,
                embedding=emb,
                frame_id=frame_id or kf.frame_id,
                meta=kf.meta,
            )
        return kf
    if isinstance(item, Mapping):
        base = RouteKeyframe.from_mapping(item)
        return _as_keyframe(base, t_s=t_s, embedder=embedder, frame_bytes=frame_bytes, frame_id=frame_id)
    if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
        if len(item) < 2:
            raise ValueError("pose sequence must be (x, y) or (x, y, yaw)")
        x = float(item[0])
        y = float(item[1])
        yaw = float(item[2]) if len(item) >= 3 else 0.0
        emb: tuple[float, ...] = ()
        if embedder is not None:
            emb = embedder.embed(
                pose=(x, y, yaw),
                frame_bytes=frame_bytes,
                frame_id=frame_id,
            )
        return RouteKeyframe(
            x=x,
            y=y,
            yaw_rad=yaw,
            t_s=t_s,
            embedding=emb,
            frame_id=frame_id,
        )
    raise TypeError("keyframe must be RouteKeyframe, mapping, or (x,y[,yaw])")


@dataclass
class TeachRepeatSession:
    """teach(path) / follow(path_id) over a shared ``RouteMemoryStore``."""

    store: RouteMemoryStore = field(default_factory=RouteMemoryStore)
    embedder: VPREmbedder | None = field(default_factory=StubVPREmbedder)
    default_ttl_s: float = 2.0
    default_priority: int = 3
    _recording: list[RouteKeyframe] = field(default_factory=list, init=False, repr=False)
    _recording_name: str = field(default="", init=False, repr=False)
    _recording_meta: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _active_followers: dict[str, RouteMemoryProposer] = field(
        default_factory=dict, init=False, repr=False
    )
    _teach_open: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.store, RouteMemoryStore):
            raise TypeError("store must be RouteMemoryStore")
        # Allow structural stubs that implement embed without Protocol runtime.
        if (
            self.embedder is not None
            and not isinstance(self.embedder, VPREmbedder)
            and not hasattr(self.embedder, "embed")
        ):
            raise TypeError("embedder must implement embed()")
        if not math.isfinite(self.default_ttl_s) or self.default_ttl_s <= 0.0:
            raise ValueError("default_ttl_s must be finite and positive")

    @property
    def is_recording(self) -> bool:
        return self._teach_open

    def begin_teach(self, *, name: str = "", meta: Mapping[str, Any] | None = None) -> None:
        if self._teach_open:
            raise RuntimeError("teach already in progress; call end_teach() first")
        self._recording = []
        self._recording_name = name
        self._recording_meta = dict(meta or {})
        self._teach_open = True

    def append_pose(
        self,
        pose: Sequence[float] | RouteKeyframe | Mapping[str, Any],
        *,
        t_s: float = 0.0,
        frame_bytes: bytes | None = None,
        frame_id: str = "",
    ) -> RouteKeyframe:
        """Append one sim-walk sample during an open teach session."""

        if not self._teach_open:
            self.begin_teach()
        kf = _as_keyframe(
            pose,
            t_s=float(t_s),
            embedder=self.embedder,
            frame_bytes=frame_bytes,
            frame_id=frame_id,
        )
        self._recording.append(kf)
        return kf

    def end_teach(
        self,
        *,
        path_id: str | None = None,
        created_s: float = 0.0,
    ) -> RoutePath:
        if not self._teach_open:
            raise RuntimeError("no teach session open")
        if not self._recording:
            raise ValueError("cannot end teach with zero keyframes")
        path = self.store.record(
            self._recording,
            path_id=path_id,
            name=self._recording_name,
            created_s=created_s,
            meta=self._recording_meta,
        )
        self._recording = []
        self._recording_name = ""
        self._recording_meta = {}
        self._teach_open = False
        return path

    def teach(
        self,
        poses: Sequence[Sequence[float] | RouteKeyframe | Mapping[str, Any]],
        *,
        path_id: str | None = None,
        name: str = "",
        created_s: float = 0.0,
        meta: Mapping[str, Any] | None = None,
        frame_bytes_seq: Sequence[bytes | None] | None = None,
        frame_ids: Sequence[str] | None = None,
    ) -> RoutePath:
        """One-shot teach from a pose sequence (sim walk / bag-derived)."""

        if not isinstance(poses, Sequence) or isinstance(poses, (str, bytes)):
            raise TypeError("poses must be a sequence")
        if not poses:
            raise ValueError("poses must be non-empty")
        if self._teach_open:
            raise RuntimeError("incremental teach in progress; end it first")
        keyframes: list[RouteKeyframe] = []
        for i, pose in enumerate(poses):
            fb = None
            if frame_bytes_seq is not None:
                fb = frame_bytes_seq[i] if i < len(frame_bytes_seq) else None
            fid = ""
            if frame_ids is not None and i < len(frame_ids):
                fid = str(frame_ids[i])
            t_s = float(i) * 0.1
            if isinstance(pose, RouteKeyframe):
                t_s = pose.t_s if pose.t_s else t_s
            elif isinstance(pose, Mapping) and "t_s" in pose:
                t_s = float(pose["t_s"])  # type: ignore[index]
            keyframes.append(
                _as_keyframe(
                    pose,
                    t_s=t_s,
                    embedder=self.embedder,
                    frame_bytes=fb,
                    frame_id=fid,
                )
            )
        return self.store.record(
            keyframes,
            path_id=path_id,
            name=name,
            created_s=created_s,
            meta=meta,
        )

    def follow(
        self,
        path_id: str,
        *,
        gate_enabled: bool = False,
        priority: int | None = None,
        ttl_s: float | None = None,
        confidence: float = 0.8,
        plan_step_id: str = "",
        lookahead_keyframes: int = 3,
        arrive_tol_m: float = 0.35,
    ) -> RouteMemoryProposer:
        """Return a gated RouteMemoryProposer for ``path_id`` (no velocity)."""

        path = self.store.require(path_id)
        proposer = RouteMemoryProposer(
            path=path,
            gate_enabled=gate_enabled,
            priority=self.default_priority if priority is None else priority,
            ttl_s=self.default_ttl_s if ttl_s is None else ttl_s,
            confidence=confidence,
            plan_step_id=plan_step_id,
            lookahead_keyframes=lookahead_keyframes,
            arrive_tol_m=arrive_tol_m,
        )
        self._active_followers[path_id] = proposer
        return proposer

    def active_follower(self, path_id: str) -> RouteMemoryProposer | None:
        return self._active_followers.get(path_id)

    def list_paths(self) -> tuple[str, ...]:
        return self.store.list_ids()
