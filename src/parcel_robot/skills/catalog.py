from __future__ import annotations

from pathlib import Path

import yaml

from parcel_robot.models import Pose

from .schema import MAX_POSE_PLAYBACK_S, SkillSpec, parse_skill, playback_timing


class SkillCatalog:
    """Loads skill YAML files under a skills root (indexed by catalog.yaml)."""

    def __init__(self, skills: dict[str, SkillSpec], *, order: tuple[str, ...]):
        self._skills = skills
        self._order = order

    @classmethod
    def load(cls, skills_root: str | Path) -> SkillCatalog:
        root = Path(skills_root)
        if not root.is_dir():
            raise FileNotFoundError(root)

        by_id: dict[str, SkillSpec] = {}
        for path in sorted(root.rglob("*.yaml")):
            if path.name == "catalog.yaml":
                continue
            with path.open(encoding="utf-8") as stream:
                data = yaml.safe_load(stream) or {}
            if not isinstance(data, dict) or "id" not in data:
                continue
            spec = parse_skill(data, source_path=str(path))
            if spec.enabled:
                by_id[spec.id] = spec

        order = cls._load_order(root, by_id)
        missing = [skill_id for skill_id in order if skill_id not in by_id]
        if missing:
            raise KeyError(f"catalog lists unknown or disabled skills: {missing}")
        return cls(by_id, order=order)

    @staticmethod
    def _load_order(root: Path, by_id: dict[str, SkillSpec]) -> tuple[str, ...]:
        catalog_path = root / "catalog.yaml"
        if catalog_path.is_file():
            with catalog_path.open(encoding="utf-8") as stream:
                data = yaml.safe_load(stream) or {}
            ids = data.get("skills") or []
            return tuple(str(skill_id) for skill_id in ids)
        return tuple(sorted(by_id))

    def ids(self) -> list[str]:
        return list(self._order)

    def get(self, skill_id: str) -> SkillSpec:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {skill_id!r}") from exc

    def list(self, tag: str | None = None, kind: str | None = None) -> list[SkillSpec]:
        specs = [self._skills[skill_id] for skill_id in self._order]
        if kind is not None:
            specs = [spec for spec in specs if spec.kind == kind]
        if tag is not None:
            specs = [spec for spec in specs if tag in spec.tags]
        return specs

    def as_pose_map(self) -> dict[str, Pose]:
        poses: dict[str, Pose] = {}
        for spec in self.list(kind="pose"):
            joints = spec.as_pose_joints()
            if joints:
                _, duration = playback_timing(
                    spec.duration,
                    spec.speed,
                    maximum_duration_s=MAX_POSE_PLAYBACK_S,
                )
                poses[spec.id] = Pose(spec.id, joints, duration=duration)
        return poses
