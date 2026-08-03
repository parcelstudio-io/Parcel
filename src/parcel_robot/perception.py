from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

ALLOWED_SPATIAL_SENSORS = frozenset({"camera", "lidar"})


class MapContextProvider(Protocol):
    def context(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class NullMapProvider:
    """Non-networking placeholder for a future Google Maps integration."""

    provider: str = "google_maps"

    def context(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "status": "placeholder",
            "available": False,
            "data": None,
        }


@dataclass(frozen=True)
class PerceptionContract:
    """Capabilities visible to reasoning, separate from simulator diagnostics."""

    spatial_sensors: tuple[str, ...] = ("camera", "lidar")
    camera_role: str = "owner/object/scene perception"
    lidar_role: str = "range, free-space, and collision perception"
    simulator_truth_diagnostics_only: bool = True

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PerceptionContract:
        raw = config.get("spatial_sensors", ["camera", "lidar"])
        if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
            raise TypeError("perception.spatial_sensors must be a non-empty list")
        sensors = tuple(dict.fromkeys(item.strip().lower() for item in raw))
        unsupported = set(sensors) - ALLOWED_SPATIAL_SENSORS
        if unsupported:
            raise ValueError(f"unsupported spatial sensors: {sorted(unsupported)}")
        if set(sensors) != ALLOWED_SPATIAL_SENSORS:
            raise ValueError("Parcel spatial perception requires camera and lidar")
        maps = config.get("maps") or {}
        if not isinstance(maps, dict):
            raise TypeError("perception.maps must be a mapping")
        if bool(maps.get("enabled", False)):
            raise ValueError("map context is a placeholder and cannot be enabled yet")
        provider = str(maps.get("provider", "google_maps"))
        if provider != "google_maps":
            raise ValueError("only the disabled google_maps placeholder is configured")
        return cls(spatial_sensors=sensors)

    def snapshot(self, maps: MapContextProvider) -> dict[str, object]:
        return {
            **asdict(self),
            "maps": maps.context(),
            "reasoning_visibility": {
                "environment": list(self.spatial_sensors),
                "simulator_ground_truth": False,
            },
        }
