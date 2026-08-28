"""Skill-catalog adapter for :mod:`parcel_robot.capabilities`.

The adapter hashes parsed motion content rather than filenames or YAML bytes:
moving a catalog does not revoke commissioning, while changing a joint, time,
tag, playback rate, or kind does.  Trajectories enter the gesture category only
when their authored tags explicitly contain ``gesture``; their names are never
interpreted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from parcel_robot.capabilities.manifest import (
    CapabilityManifestV1,
    GestureCapabilityV1,
    PoseCapabilityV1,
    ToolCapabilityV1,
    canonical_digest,
)

from .catalog import SkillCatalog
from .schema import SkillSpec


def skill_trajectory_payload(skill: SkillSpec) -> dict[str, object]:
    """Canonical motion fields whose changes invalidate commissioning."""

    payload: dict[str, object] = {
        "format": "parcel-skill-trajectory-v1",
        "id": skill.id,
        "kind": skill.kind,
        "tags": sorted(skill.tags),
        "duration": skill.duration,
        "speed": skill.speed,
    }
    if skill.kind == "pose":
        payload["joints"] = {name: value for name, value in sorted(skill.joints.items())}
    elif skill.kind == "trajectory":
        payload["keyframes"] = [
            {
                "t": frame.t,
                "joints": {name: value for name, value in sorted(frame.joints.items())},
            }
            for frame in skill.keyframes
        ]
    else:
        raise ValueError(
            f"trajectory digest requires a pose or trajectory skill, got {skill.kind!r}"
        )
    return payload


def skill_trajectory_digest(skill: SkillSpec) -> str:
    return canonical_digest(skill_trajectory_payload(skill))


def motion_capability_declarations(
    catalog: SkillCatalog,
) -> tuple[tuple[GestureCapabilityV1, ...], tuple[PoseCapabilityV1, ...]]:
    """Return typed gesture/pose declarations from explicit catalog metadata."""

    gestures: list[GestureCapabilityV1] = []
    poses: list[PoseCapabilityV1] = []
    for skill in catalog.list():
        if skill.kind == "pose":
            poses.append(
                PoseCapabilityV1(
                    name=skill.id,
                    tags=skill.tags,
                    trajectory_digest=skill_trajectory_digest(skill),
                )
            )
        elif skill.kind == "trajectory" and "gesture" in skill.tags:
            gestures.append(
                GestureCapabilityV1(
                    name=skill.id,
                    tags=skill.tags,
                    trajectory_digest=skill_trajectory_digest(skill),
                )
            )
    return tuple(gestures), tuple(poses)


def validate_motion_manifest(
    manifest: CapabilityManifestV1,
    catalog: SkillCatalog,
) -> None:
    """Refuse a manifest whose typed motion facts differ from the live catalog."""

    gestures, poses = motion_capability_declarations(catalog)
    expected_gestures = {entry.name: entry for entry in gestures}
    expected_poses = {entry.name: entry for entry in poses}
    for kind, entries, expected in (
        ("gesture", manifest.gestures, expected_gestures),
        ("pose", manifest.poses, expected_poses),
    ):
        for entry in entries:
            declared = expected.get(entry.name)
            if declared is None:
                raise ValueError(
                    f"capability manifest {kind} {entry.name!r} is absent from the live catalog"
                )
            if (
                entry.tags != declared.tags
                or entry.trajectory_digest != declared.trajectory_digest
            ):
                raise ValueError(
                    f"capability manifest {kind} {entry.name!r} does not match "
                    "the live catalog tags/trajectory digest"
                )


def tool_capability_declarations(
    definitions: Sequence[Mapping[str, Any]],
    *,
    tags_by_name: Mapping[str, Sequence[str]] | None = None,
) -> tuple[ToolCapabilityV1, ...]:
    """Bind exact model tool schemas; malformed/duplicate definitions refuse."""

    tags = tags_by_name or {}
    result: list[ToolCapabilityV1] = []
    names: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, Mapping):
            raise TypeError("tool definitions must be mappings")
        unknown = set(definition) - {"name", "description", "parameters"}
        if unknown:
            raise ValueError(f"unsupported tool definition fields: {sorted(unknown)}")
        try:
            name = definition["name"]
            parameters = definition["parameters"]
        except KeyError as error:
            raise ValueError("tool definition requires name and parameters") from error
        if not isinstance(name, str):
            raise TypeError("tool definition name must be a string")
        if name in names:
            raise ValueError(f"duplicate tool definition: {name}")
        if not isinstance(parameters, Mapping):
            raise TypeError(f"tool {name!r} parameters must be a mapping")
        names.add(name)
        result.append(
            ToolCapabilityV1(
                name=name,
                schema_digest=canonical_digest(dict(parameters)),
                tags=tuple(tags.get(name, ())),
            )
        )
    unknown_tags = sorted(set(tags) - names)
    if unknown_tags:
        raise ValueError(f"tool tags name undefined tools: {unknown_tags}")
    return tuple(sorted(result, key=lambda entry: entry.name))


__all__ = [
    "motion_capability_declarations",
    "skill_trajectory_digest",
    "skill_trajectory_payload",
    "tool_capability_declarations",
    "validate_motion_manifest",
]
