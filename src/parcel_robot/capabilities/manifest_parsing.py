"""Strict serialized capability-row parsing without manifest import cycles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def manifest_rows(
    value: Mapping[str, Any], field_name: str, error_type: type[ValueError]
) -> list[Mapping[str, Any]]:
    raw = value[field_name]
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise error_type(f"manifest {field_name} must be a sequence")
    if not all(isinstance(row, Mapping) for row in raw):
        raise error_type(f"manifest {field_name} must contain mappings")
    return list(raw)


def _exact(
    row: Mapping[str, Any], names: set[str], label: str, error_type: type[ValueError]
) -> None:
    if set(row) != names:
        raise error_type(
            f"{label} fields must be exactly {sorted(names)}, got {sorted(row)}"
        )


def _uncommissioned(row: Mapping[str, Any], error_type: type[ValueError]) -> None:
    if row["commissioned"] is not False:
        raise error_type(
            "serialized commissioned state is untrusted; regenerate from commissioning"
        )


def parse_tool_rows(rows, entry_type, error_type):
    result = []
    fields = {"name", "schema_digest", "tags", "commissioned"}
    for row in rows:
        _exact(row, fields, "tool", error_type)
        _uncommissioned(row, error_type)
        result.append(
            entry_type(
                name=row["name"], schema_digest=row["schema_digest"], tags=tuple(row["tags"])
            )
        )
    return tuple(result)


def parse_gesture_rows(rows, entry_type, error_type):
    result = []
    fields = {"name", "tags", "trajectory_digest", "commissioned"}
    for row in rows:
        _exact(row, fields, "gesture", error_type)
        _uncommissioned(row, error_type)
        result.append(
            entry_type(
                name=row["name"],
                tags=tuple(row["tags"]),
                trajectory_digest=row["trajectory_digest"],
            )
        )
    return tuple(result)


def parse_pose_rows(rows, entry_type, error_type):
    result = []
    fields = {"name", "tags", "trajectory_digest", "commissioned"}
    for row in rows:
        _exact(row, fields, "pose", error_type)
        _uncommissioned(row, error_type)
        result.append(
            entry_type(
                name=row["name"],
                tags=tuple(row["tags"]),
                trajectory_digest=row["trajectory_digest"],
            )
        )
    return tuple(result)


def parse_navigation_rows(rows, entry_type, error_type):
    result = []
    fields = {"name", "tags", "required_evidence", "commissioned"}
    for row in rows:
        _exact(row, fields, "navigation mode", error_type)
        _uncommissioned(row, error_type)
        result.append(
            entry_type(
                name=row["name"],
                tags=tuple(row["tags"]),
                required_evidence=tuple(row["required_evidence"]),
            )
        )
    return tuple(result)
