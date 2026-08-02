from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from .models import ModuleSpec, Pose, WifiCard
from .safety import SafetyLimits


class ConfigStore:
    """Loads user-editable poses, network cards, and extension modules."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self.path.open(encoding="utf-8") as stream:
            self.data: dict[str, Any] = yaml.safe_load(stream) or {}

    def poses(self) -> dict[str, Pose]:
        legacy = {
            name: Pose(
                name=name,
                joints={joint: float(value) for joint, value in item["joints"].items()},
                duration=float(item.get("duration", 1.0)),
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
        if not configured:
            configured = "configs/skills"
        path = Path(str(configured)).expanduser()
        if path.is_absolute():
            return path
        bases = [self.path.parent.parent, Path.cwd()]
        if len(self.path.parents) >= 4:
            bases.insert(0, self.path.parents[3])
        for base in bases:
            candidate = (base / path).resolve()
            if candidate.is_dir():
                return candidate
        return (Path.cwd() / path).resolve()

    def motion_config(self) -> dict[str, Any]:
        return self.section("motion") if "motion" in self.data else {"backend": "rl"}

    def safety_limits(self) -> SafetyLimits:
        motion = self.motion_config()
        return SafetyLimits(
            max_vx=float(motion.get("max_vx", 0.6)),
            max_vy=float(motion.get("max_vy", 0.4)),
            max_vyaw=float(motion.get("max_vyaw", 1.0)),
        )

    def wifi_cards(self) -> dict[str, WifiCard]:
        return {
            name: WifiCard(
                name=name,
                interface=str(item["interface"]),
                ros_domain_id=int(item.get("ros_domain_id", 0)),
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
