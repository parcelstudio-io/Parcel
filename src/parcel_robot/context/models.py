from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

CONTEXT_KINDS = ("location", "time", "map", "scene")


@dataclass(frozen=True)
class ContextField:
    kind: str
    source: str
    observed_at: datetime
    value: dict[str, Any]
    accuracy_m: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in CONTEXT_KINDS:
            raise ValueError(f"unsupported context kind: {self.kind!r}")
        if not self.source or len(self.source) > 80:
            raise ValueError("context source must be a short non-empty string")
        if self.observed_at.tzinfo is None:
            raise ValueError("context observed_at must be timezone-aware")
        if not isinstance(self.value, dict):
            raise TypeError("context value must be a mapping")
        if self.accuracy_m is not None and (
            not math.isfinite(self.accuracy_m) or self.accuracy_m < 0.0
        ):
            raise ValueError("context accuracy_m must be finite and non-negative")

    def age_s(self, now: datetime) -> float:
        return max(0.0, (now.astimezone(UTC) - self.observed_at.astimezone(UTC)).total_seconds())


@dataclass(frozen=True)
class ContextBuildConfig:
    enabled: bool = False
    timeout_ms: int = 150
    max_age_s: float = 2.0
    enable_location_context: bool = False
    enable_time_context: bool = False
    enable_map_context: bool = False
    enable_scene_context: bool = False
    include_precise_coordinates_in_prompt: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> ContextBuildConfig:
        data = dict(raw or {})
        config = cls(
            enabled=bool(data.get("enabled", False)),
            timeout_ms=int(data.get("timeout_ms", 150)),
            max_age_s=float(data.get("max_age_s", 2.0)),
            enable_location_context=bool(data.get("enable_location_context", False)),
            enable_time_context=bool(data.get("enable_time_context", False)),
            enable_map_context=bool(data.get("enable_map_context", False)),
            enable_scene_context=bool(data.get("enable_scene_context", False)),
            include_precise_coordinates_in_prompt=bool(
                data.get("include_precise_coordinates_in_prompt", False)
            ),
        )
        if not 10 <= config.timeout_ms <= 10_000:
            raise ValueError("query_context.timeout_ms must be between 10 and 10000")
        if not math.isfinite(config.max_age_s) or config.max_age_s <= 0.0:
            raise ValueError("query_context.max_age_s must be positive and finite")
        return config

    def enabled_kinds(self) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        return tuple(
            kind for kind in CONTEXT_KINDS if bool(getattr(self, f"enable_{kind}_context"))
        )


@dataclass(frozen=True)
class ContextSnapshot:
    generated_at: datetime
    fields: dict[str, ContextField] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def field(self, kind: str) -> ContextField | None:
        return self.fields.get(kind)

    def navigation_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            **{
                kind: {
                    **item.value,
                    "source": item.source,
                    "observed_at": item.observed_at.isoformat(),
                    **({"accuracy_m": item.accuracy_m} if item.accuracy_m is not None else {}),
                }
                for kind, item in self.fields.items()
            },
            **({"errors": dict(self.errors)} if self.errors else {}),
        }

    def prompt_data(self, *, include_precise_coordinates: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
        }
        for kind, item in self.fields.items():
            value = _prompt_safe(item.value)
            if kind == "location" and not include_precise_coordinates:
                for key in ("latitude", "longitude", "x", "y", "z", "coordinates"):
                    value.pop(key, None)
            result[kind] = {
                "data": value,
                "source": item.source,
                "observed_at": item.observed_at.isoformat(),
            }
        if self.errors:
            result["unavailable"] = sorted(self.errors)
        return result


def _prompt_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Allow bounded JSON data into the prompt; never forward arbitrary objects."""

    def clean(item: Any, depth: int = 0) -> Any:
        if depth > 4:
            return None
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else None
        if isinstance(item, str):
            return item[:300]
        if isinstance(item, (list, tuple)):
            return [clean(entry, depth + 1) for entry in item[:32]]
        if isinstance(item, dict):
            return {
                str(key)[:80]: clean(entry, depth + 1) for key, entry in list(item.items())[:32]
            }
        return str(item)[:120]

    return clean(value)
