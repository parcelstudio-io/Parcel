"""Strict, canonical and immutable contracts for offline simulator learning."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = 1
SPLITS = frozenset({"train", "dev", "frozen_test"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class LearningContractError(ValueError):
    """A learning-plane boundary value is malformed or contradictory."""


def exact(data: Mapping[str, object], fields: set[str], name: str) -> None:
    if not isinstance(data, Mapping):
        raise LearningContractError(f"{name} must be a mapping")
    missing = fields - set(data)
    extra = set(data) - fields
    if missing:
        raise LearningContractError(f"{name} missing fields: {sorted(missing)}")
    if extra:
        raise LearningContractError(f"{name} has unknown fields: {sorted(extra)}")


def integer(value: object, name: str, *, maximum: int = (1 << 63) - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningContractError(f"{name} must be an integer")
    if value < 0 or value > maximum:
        raise LearningContractError(f"{name} must be between 0 and {maximum}")
    return value


def finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LearningContractError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise LearningContractError(f"{name} must be finite")
    return result


def boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise LearningContractError(f"{name} must be a boolean")
    return value


def identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise LearningContractError(f"{name} must be a bounded identifier")
    return value


def digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise LearningContractError(f"{name} must be a lowercase SHA-256 digest")
    return value


def sequence(value: object, name: str, *, maximum: int = 10_000) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise LearningContractError(f"{name} must be a sequence")
    if len(value) > maximum:
        raise LearningContractError(f"{name} exceeds {maximum} items")
    return value


def string_tuple(value: object, name: str, *, maximum: int = 256) -> tuple[str, ...]:
    items = tuple(identifier(item, f"{name} item") for item in sequence(value, name, maximum=maximum))
    if len(set(items)) != len(items):
        raise LearningContractError(f"{name} cannot contain duplicates")
    return tuple(sorted(items))


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise LearningContractError(f"value is not canonical JSON: {error}") from error


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require_version(value: object, name: str) -> int:
    version = integer(value, f"{name} schema_version")
    if version != SCHEMA_VERSION:
        raise LearningContractError(f"{name} schema_version must equal {SCHEMA_VERSION}")
    return version


def as_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LearningContractError(f"{name} must be a mapping")
    return value
