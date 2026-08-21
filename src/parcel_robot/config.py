from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .models import ModuleSpec, Pose, WifiCard
from .safety import SafetyLimitError, SafetyLimits


class ConfigStore:
    """Loads user-editable poses, network cards, and extension modules.

    FAIL-CLOSED NUMERICS (card R23)
    -------------------------------
    Every numeric key this loader coerces is validated here, at the boundary,
    with an error that names the file, the dotted key, and the offending
    value. The doctrine is ``realtime/config.py``'s and the reason is the same:
    a typo that silently reads as "no limit" is worse than a typo that refuses
    to start. It matters most for the velocity clamps, because a NaN there is
    not a wrong clamp — it is no clamp, at both enforcement sites at once.

    ``configs/robot.yaml`` is digest-pinned and passes this validation
    unchanged; nothing here alters an effective limit on the shipped config.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self.path.open(encoding="utf-8") as stream:
            self.data: dict[str, Any] = yaml.safe_load(stream) or {}

    # ------------------------------------------------------------------
    # Fail-closed numeric coercion (card R23)
    # ------------------------------------------------------------------

    def _number(self, value: object, key: str) -> float:
        """Coerce one config value to a real number or refuse by name."""

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SafetyLimitError(f"{self.path}: {key} must be a number, got {value!r}")
        number = float(value)
        if not math.isfinite(number):
            raise SafetyLimitError(
                f"{self.path}: {key} must be finite, got {number}. A non-finite "
                f"value here is not a loose setting, it is an absent one."
            )
        return number

    def _positive_number(self, mapping: Mapping[str, Any], key: str, default: float, path: str) -> float:
        """A finite, strictly positive config number, named by its dotted key."""

        number = self._number(mapping.get(key, default), path)
        if number <= 0.0:
            raise SafetyLimitError(
                f"{self.path}: {path} must be greater than zero, got {number}. "
                f"A zero or negative clamp reads as a typo, not as intent."
            )
        return number

    def _whole_number(self, mapping: Mapping[str, Any], key: str, default: int, path: str) -> int:
        """A non-negative whole number. ``True`` is not 1 and 2.5 is not 2."""

        value = mapping.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SafetyLimitError(f"{self.path}: {path} must be a whole number, got {value!r}")
        if isinstance(value, float) and (not math.isfinite(value) or value != int(value)):
            raise SafetyLimitError(f"{self.path}: {path} must be a whole number, got {value!r}")
        number = int(value)
        if number < 0:
            raise SafetyLimitError(f"{self.path}: {path} must not be negative, got {number}")
        return number

    def poses(self) -> dict[str, Pose]:
        legacy = {
            name: Pose(
                name=name,
                joints={
                    joint: self._number(value, f"poses.{name}.joints.{joint}")
                    for joint, value in item["joints"].items()
                },
                duration=self._positive_number(item, "duration", 1.0, f"poses.{name}.duration"),
            )
            for name, item in self.data.get("poses", {}).items()
        }
        try:
            from parcel_robot.skills.catalog import SkillCatalog

            catalog = SkillCatalog.load(self.skills_root())
            poses = catalog.as_pose_map()
            poses.update(legacy)
            return poses
        except (FileNotFoundError, OSError, KeyError, ValueError, TypeError):
            return legacy

    def skills_root(self) -> Path:
        configured = None
        if "skills" in self.data and isinstance(self.data["skills"], dict):
            configured = self.data["skills"].get("root")
        from parcel_robot.paths import resolve_skills_root

        try:
            return resolve_skills_root(str(configured) if configured else None)
        except FileNotFoundError:
            # Preserve historical cwd fallback for ad-hoc local layouts.
            path = Path(str(configured or "configs/skills")).expanduser()
            if path.is_absolute():
                return path
            return (Path.cwd() / path).resolve()

    def motion_config(self) -> dict[str, Any]:
        return self.section("motion") if "motion" in self.data else {"backend": "rl"}

    def agent_config(self) -> dict[str, Any]:
        return self.section("agent") if "agent" in self.data else {}

    def prompts_root(self) -> Path:
        configured = self.agent_config().get("prompts_root", "prompts")
        from parcel_robot.paths import resolve_prompts_root

        try:
            return resolve_prompts_root(str(configured) if configured else None)
        except FileNotFoundError:
            path = Path(str(configured or "prompts")).expanduser()
            if path.is_absolute():
                return path.resolve()
            return (Path.cwd() / path).resolve()

    def safety_limits(self) -> SafetyLimits:
        """The velocity clamp both enforcement sites compare against.

        Card R23: previously a bare ``float()``, which turned ``max_vx: .nan``
        into a silently disabled clamp in the arbiter AND the
        SafetySupervisor. The defaults below are deliberately left at the
        historical (0.6, 0.4, 1.0) — they are the loader's fallback, not the
        dataclass's, and changing them is a threshold change this card does
        not make.
        """

        motion = self.motion_config()
        return SafetyLimits(
            max_vx=self._positive_number(motion, "max_vx", 0.6, "motion.max_vx"),
            max_vy=self._positive_number(motion, "max_vy", 0.4, "motion.max_vy"),
            max_vyaw=self._positive_number(motion, "max_vyaw", 1.0, "motion.max_vyaw"),
        )

    def wifi_cards(self) -> dict[str, WifiCard]:
        return {
            name: WifiCard(
                name=name,
                interface=str(item["interface"]),
                ros_domain_id=self._whole_number(
                    item, "ros_domain_id", 0, f"wifi_cards.{name}.ros_domain_id"
                ),
                purpose=str(item.get("purpose", "robot")),
            )
            for name, item in self.data.get("wifi_cards", {}).items()
        }

    def module_specs(self) -> list[ModuleSpec]:
        return [
            ModuleSpec(
                name=str(item["name"]),
                class_path=str(item["class"]),
                enabled=bool(item.get("enabled", True)),
                config=dict(item.get("config", {})),
            )
            for item in self.data.get("modules", [])
        ]

    def load_modules(self) -> list[Any]:
        modules = []
        for spec in self.module_specs():
            if not spec.enabled:
                continue
            module_name, class_name = spec.class_path.rsplit(".", 1)
            module_class = getattr(importlib.import_module(module_name), class_name)
            modules.append(module_class(spec.config))
        return modules

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        if not isinstance(value, dict):
            raise TypeError(f"configuration section {name!r} must be a mapping")
        return dict(value)
