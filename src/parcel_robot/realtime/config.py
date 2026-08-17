"""Fail-closed loader for the optional ``configs/realtime.yaml`` (card R1).

WHY A SEPARATE FILE AND NOT A ``robot.yaml`` SECTION
----------------------------------------------------
``configs/robot.yaml`` is hash-locked: the embodied-plan eval manifest and the
gate's ``DIGEST_SENTINELS`` both pin its bytes, so one added key moves two
frozen digests and reddens a hard gate. The lane's config is therefore a NEW,
OPTIONAL file. Its absence is not an error — it is the shipped default, and it
means the lane does not construct at all. Flag-off is *file-absent*, which is
the strongest form of "off" available: there is nothing to misread.

FAIL-CLOSED, THE SAME WAY EVERY OTHER CONFIG SURFACE HERE DOES
--------------------------------------------------------------
``providers.py`` refuses unknown ``speech:`` keys; ``resolve_allow_monitor_capture``
raises on a non-boolean. A typo'd ``enabled: ture`` that silently read as false
would be a bad day; a typo'd ``monthly_budget_usd`` that silently read as
"unlimited" would be a worse one. Unknown keys raise, wrong types raise, and
negative budgets raise.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.paths import resolve_asset

#: Repo-relative location the runtime looks for. Deliberately NOT created by
#: this card and deliberately NOT in the packaged ship set for R1.
REALTIME_CONFIG_RELATIVE = ("configs", "realtime.yaml")

#: Test / operator override, so a tmp_path config can be exercised without ever
#: writing a file into the repo.
REALTIME_CONFIG_ENV = "PARCEL_REALTIME_CONFIG"

#: The whole schema. Anything else is a typo, and a typo is a refusal.
ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "model",
        "voice",
        "stall_timeout_s",
        "session_max_s",
        "monthly_budget_usd",
    }
)


class RealtimeConfigError(ValueError):
    """A realtime config that cannot be trusted. Never downgraded to a default."""


@dataclass(frozen=True)
class RealtimeConfig:
    """The lane's entire configuration surface."""

    enabled: bool = False
    model: str = "gpt-realtime-2.1"
    voice: str = "cedar"
    stall_timeout_s: float = 8.0
    session_max_s: float = 3600.0
    monthly_budget_usd: float = 25.0
    source: str = "absent"

    @property
    def present(self) -> bool:
        """Did a config file actually exist? (``enabled`` can still be false.)"""

        return self.source != "absent"

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "voice": self.voice,
            "stall_timeout_s": self.stall_timeout_s,
            "session_max_s": self.session_max_s,
            "monthly_budget_usd": self.monthly_budget_usd,
            "source": self.source,
        }


def _boolean(mapping: Mapping[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if isinstance(value, bool):
        return value
    raise RealtimeConfigError(f"realtime.{key} must be a boolean, got {value!r}")


def _text(mapping: Mapping[str, Any], key: str, default: str) -> str:
    value = mapping.get(key, default)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RealtimeConfigError(f"realtime.{key} must be a non-empty string, got {value!r}")


def _positive(mapping: Mapping[str, Any], key: str, default: float) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(f"realtime.{key} must be a number, got {value!r}")
    number = float(value)
    if not number > 0.0:
        raise RealtimeConfigError(f"realtime.{key} must be greater than zero, got {number}")
    return number


def realtime_config_from_mapping(
    mapping: Mapping[str, Any] | None,
    *,
    source: str = "mapping",
) -> RealtimeConfig:
    """Validate one already-parsed config body. Unknown keys refuse."""

    if mapping is None:
        return RealtimeConfig(source=source)
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime config must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime config key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(ALLOWED_KEYS))}"
        )
    return RealtimeConfig(
        enabled=_boolean(mapping, "enabled", False),
        model=_text(mapping, "model", "gpt-realtime-2.1"),
        voice=_text(mapping, "voice", "cedar"),
        stall_timeout_s=_positive(mapping, "stall_timeout_s", 8.0),
        session_max_s=_positive(mapping, "session_max_s", 3600.0),
        monthly_budget_usd=_positive(mapping, "monthly_budget_usd", 25.0),
        source=source,
    )


def load_realtime_config(path: str | Path | None) -> RealtimeConfig:
    """Read one config file. A missing path is a DISABLED config, not an error."""

    if path is None:
        return RealtimeConfig(source="absent")
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        return RealtimeConfig(source="absent")
    try:
        body = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise RealtimeConfigError(f"realtime config is not valid YAML: {resolved}") from error
    if body is None:
        return RealtimeConfig(source=str(resolved))
    return realtime_config_from_mapping(body, source=str(resolved))


def resolve_realtime_config_path() -> Path | None:
    """Where the runtime looks. ``None`` when no config file exists anywhere.

    The environment override exists so tests (and an operator running two
    profiles) can point at a file without one ever being added to the repo —
    R1's shipped default is *no file*.
    """

    override = os.environ.get(REALTIME_CONFIG_ENV, "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    try:
        return resolve_asset(*REALTIME_CONFIG_RELATIVE, kind="file")
    except FileNotFoundError:
        return None


def default_realtime_config() -> RealtimeConfig:
    """The config the runtime boots with. Absent file ⇒ the lane never builds."""

    return load_realtime_config(resolve_realtime_config_path())


__all__ = [
    "ALLOWED_KEYS",
    "REALTIME_CONFIG_ENV",
    "REALTIME_CONFIG_RELATIVE",
    "RealtimeConfig",
    "RealtimeConfigError",
    "default_realtime_config",
    "load_realtime_config",
    "realtime_config_from_mapping",
    "resolve_realtime_config_path",
]
