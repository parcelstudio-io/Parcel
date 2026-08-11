"""CityWalker inference adapter — fail-closed, offline / skip-honest.

Binding (ADJUDICATION D7 / P4): CityWalker A/B vs OSM-graph-only. Learned
outputs are SE2Goal proposals only — never model-authored velocity. Missing
``third_party/CityWalker``, weights, or torch → skip with UNVERIFIED; CI must
not break.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.paths import parcel_roots

PROPOSER_SOURCE = "citywalker_v1"
DEFAULT_CHECKPOINT_REL = Path("models/nav/citywalker/CityWalker_2000hr.ckpt")
DEFAULT_VENDOR_REL = Path("third_party/CityWalker")

StatusKind = Literal["ready", "skipped", "error"]

DOES_NOT_PROVE = (
    (
        "CityWalkerInferenceAdapter is a fail-closed interface over vendored "
        "CityWalker + optional checkpoint; absent weights/torch/vendor skip "
        "with UNVERIFIED and do not prove urban IL SR, Orin budgets, or "
        "promotion ≥+5pp (HR-13)."
    ),
)


def _repo_candidates() -> tuple[Path, ...]:
    roots = list(parcel_roots())
    # parcel_roots may include packaged assets; also try inferred checkout.
    package = Path(__file__).resolve().parents[3]  # …/src/parcel_robot/route_memory → repo
    if package not in roots:
        roots.append(package)
    # Dedup
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return tuple(out)


def resolve_citywalker_vendor() -> Path | None:
    for root in _repo_candidates():
        candidate = (root / DEFAULT_VENDOR_REL).resolve()
        if candidate.is_dir() and (candidate / "model").is_dir():
            return candidate
    return None


def resolve_citywalker_checkpoint() -> Path | None:
    for root in _repo_candidates():
        candidate = (root / DEFAULT_CHECKPOINT_REL).resolve()
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True, slots=True)
class CityWalkerObservation:
    """Minimal observation for offline / cached inference (no live pixels required)."""

    robot_x: float
    robot_y: float
    robot_yaw: float = 0.0
    goal_x: float | None = None
    goal_y: float | None = None
    rgb_meta: Mapping[str, Any] = field(default_factory=dict)
    cached_waypoints: tuple[tuple[float, float], ...] = ()
    t_s: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("robot_x", self.robot_x),
            ("robot_y", self.robot_y),
            ("robot_yaw", self.robot_yaw),
            ("t_s", self.t_s),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        for name, value in (("goal_x", self.goal_x), ("goal_y", self.goal_y)):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric or None")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not isinstance(self.rgb_meta, Mapping):
            raise TypeError("rgb_meta must be a mapping")
        if not isinstance(self.cached_waypoints, tuple):
            raise TypeError("cached_waypoints must be a tuple")
        for wp in self.cached_waypoints:
            if len(wp) != 2 or not all(math.isfinite(float(v)) for v in wp):
                raise ValueError("cached waypoints must be finite (x, y)")


@dataclass(frozen=True, slots=True)
class CityWalkerResult:
    status: StatusKind
    reason: str
    goal: SE2Goal | None = None
    unverified: bool = True
    does_not_prove: tuple[str, ...] = DOES_NOT_PROVE
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "goal": self.goal.as_dict() if self.goal is not None else None,
            "unverified": self.unverified,
            "does_not_prove": list(self.does_not_prove),
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class CityWalkerAdapterConfig:
    """Fail-closed config. ``gate_enabled`` defaults False (promotion rule)."""

    gate_enabled: bool = False
    require_vendor: bool = True
    require_checkpoint: bool = True
    require_torch: bool = True
    allow_cached_offline: bool = True
    priority: int = 1  # below OSM / route_memory until promotion earns more
    ttl_s: float = 1.5
    confidence: float = 0.55
    plan_step_id: str = ""
    max_waypoint_step_m: float = 4.0


class CityWalkerInferenceAdapter:
    """Fail-closed CityWalker proposer interface.

    Modes (first match):
    1. Gate off → skip (honest; default).
    2. Vendor / checkpoint / torch missing → skip UNVERIFIED (CI-safe).
    3. Cached offline waypoints present → emit SE2Goal (still gated + UNVERIFIED
       for real CityWalker weights path).
    4. Live torch inference → not wired in MVP; returns skip with reason.
    """

    def __init__(self, config: CityWalkerAdapterConfig | None = None) -> None:
        self._config = config if config is not None else CityWalkerAdapterConfig()
        self._vendor = resolve_citywalker_vendor()
        self._checkpoint = resolve_citywalker_checkpoint()
        self._torch_ok = self._probe_torch() if self._config.require_torch else True

    @property
    def config(self) -> CityWalkerAdapterConfig:
        return self._config

    @property
    def vendor_path(self) -> Path | None:
        return self._vendor

    @property
    def checkpoint_path(self) -> Path | None:
        return self._checkpoint

    @staticmethod
    def _probe_torch() -> bool:
        """Fail-soft torch probe: a broken torch is *unavailable*, not fatal.

        Narrowing this to ``ImportError`` breaks the adapter's contract. torch
        is a compiled extension: a CUDA/driver mismatch or a bad ``.so`` raises
        ``OSError`` or ``RuntimeError``, not ``ImportError``. Those must land on
        the documented ``UNVERIFIED: torch unavailable`` skip below rather than
        propagating out of ``__init__`` and taking down every caller that merely
        *constructed* the adapter on a machine with a broken install.
        """

        try:
            import torch  # noqa: F401

            return True
        except (ImportError, OSError, RuntimeError):
            return False

    def availability(self) -> dict[str, Any]:
        return {
            "gate_enabled": self._config.gate_enabled,
            "vendor_present": self._vendor is not None,
            "vendor_path": str(self._vendor) if self._vendor else None,
            "checkpoint_present": self._checkpoint is not None,
            "checkpoint_path": str(self._checkpoint) if self._checkpoint else None,
            "torch_ok": self._torch_ok,
            "allow_cached_offline": self._config.allow_cached_offline,
            "does_not_prove": list(DOES_NOT_PROVE),
            "unverified": True,
        }

    def _skip(self, reason: str, **detail: Any) -> CityWalkerResult:
        return CityWalkerResult(
            status="skipped",
            reason=reason,
            goal=None,
            unverified=True,
            detail=detail,
        )

    def propose(self, observation: CityWalkerObservation, *, now_s: float) -> CityWalkerResult:
        if not isinstance(observation, CityWalkerObservation):
            raise TypeError("observation must be CityWalkerObservation")
        if isinstance(now_s, bool) or not isinstance(now_s, (int, float)):
            raise TypeError("now_s must be numeric")
        if not math.isfinite(float(now_s)):
            raise ValueError("now_s must be finite")

        if not self._config.gate_enabled:
            return self._skip("gate_disabled", gate_enabled=False)

        # Offline / recorded-sim path first: CI-safe without torch/weights.
        if self._config.allow_cached_offline and observation.cached_waypoints:
            if self._config.require_vendor and self._vendor is None:
                # Vendor tree is the license/registry anchor even for cached A/B.
                return self._skip(
                    "UNVERIFIED: third_party/CityWalker missing",
                    vendor_present=False,
                )
            return self._from_cached(observation, now_s=float(now_s))

        if self._config.require_vendor and self._vendor is None:
            return self._skip(
                "UNVERIFIED: third_party/CityWalker missing",
                vendor_present=False,
            )
        if self._config.require_checkpoint and self._checkpoint is None:
            return self._skip(
                "UNVERIFIED: CityWalker checkpoint missing",
                checkpoint_present=False,
            )
        if self._config.require_torch and not self._torch_ok:
            return self._skip(
                "UNVERIFIED: torch unavailable for CityWalker inference",
                torch_ok=False,
            )

        # Live weight path intentionally not executed in CI MVP — honest skip.
        return self._skip(
            "UNVERIFIED: live CityWalker weight inference not wired in MVP; "
            "provide cached_waypoints for offline sim A/B",
            vendor_present=self._vendor is not None,
            checkpoint_present=self._checkpoint is not None,
            torch_ok=self._torch_ok,
        )

    def _from_cached(
        self,
        observation: CityWalkerObservation,
        *,
        now_s: float,
    ) -> CityWalkerResult:
        wps = observation.cached_waypoints
        # Bound step length — fail closed on absurd jumps.
        prev = (observation.robot_x, observation.robot_y)
        bounded: list[tuple[float, float]] = []
        for wp in wps:
            step = math.hypot(wp[0] - prev[0], wp[1] - prev[1])
            if step > self._config.max_waypoint_step_m:
                return CityWalkerResult(
                    status="error",
                    reason=(
                        f"cached waypoint step {step:.2f} m exceeds "
                        f"max_waypoint_step_m={self._config.max_waypoint_step_m}"
                    ),
                    goal=None,
                    unverified=True,
                    detail={"bad_waypoint": list(wp), "step_m": step},
                )
            bounded.append((float(wp[0]), float(wp[1])))
            prev = wp
        if not bounded:
            return self._skip("empty cached_waypoints after filter")
        tip = bounded[-1]
        if len(bounded) >= 2:
            yaw = math.atan2(tip[1] - bounded[-2][1], tip[0] - bounded[-2][0])
        else:
            yaw = observation.robot_yaw
        goal = SE2Goal(
            source=PROPOSER_SOURCE,
            pose=(tip[0], tip[1], yaw),
            waypoints=tuple(bounded) if len(bounded) > 1 else (),
            confidence=self._config.confidence,
            ttl_s=self._config.ttl_s,
            plan_step_id=self._config.plan_step_id,
            issued_s=now_s,
            priority=self._config.priority,
        )
        return CityWalkerResult(
            status="ready",
            reason="cached_offline_waypoints",
            goal=goal,
            unverified=True,
            detail={
                "mode": "cached_offline",
                "waypoint_count": len(bounded),
                "note": "SE2Goal only; not model-authored velocity",
            },
        )

    def as_bus_proposer(self, *, observation_fn):
        """ProposerBus adapter; ``observation_fn(now_s=..., **ctx)`` → observation."""

        def _propose(*, now_s: float, **ctx: Any) -> SE2Goal | None:
            obs = observation_fn(now_s=now_s, **ctx)
            result = self.propose(obs, now_s=now_s)
            return result.goal

        return _propose


def load_cached_walk(path: Path | str) -> tuple[CityWalkerObservation, ...]:
    """Load recorded sim-walk / public-sample JSON for offline adapter tests.

    Expected shape::

        {"observations": [{"robot_x", "robot_y", "robot_yaw"?, "cached_waypoints"? …}]}
    """

    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"cached CityWalker walk missing: {file_path}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise TypeError("cached walk JSON must be an object")
    raw = data.get("observations")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise TypeError("observations must be a sequence")
    out: list[CityWalkerObservation] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("each observation must be a mapping")
        wps_raw = item.get("cached_waypoints", ())
        if wps_raw is None:
            wps_raw = ()
        if not isinstance(wps_raw, Sequence) or isinstance(wps_raw, (str, bytes)):
            raise TypeError("cached_waypoints must be a sequence")
        wps = tuple((float(wp[0]), float(wp[1])) for wp in wps_raw)
        out.append(
            CityWalkerObservation(
                robot_x=float(item["robot_x"]),
                robot_y=float(item["robot_y"]),
                robot_yaw=float(item.get("robot_yaw", 0.0)),
                goal_x=float(item["goal_x"]) if item.get("goal_x") is not None else None,
                goal_y=float(item["goal_y"]) if item.get("goal_y") is not None else None,
                rgb_meta=dict(item.get("rgb_meta") or {}),
                cached_waypoints=wps,
                t_s=float(item.get("t_s", 0.0)),
            )
        )
    return tuple(out)
