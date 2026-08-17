"""Frozen N24 gateway invariant and seeded-fault inventories.

This loader validates inventory integrity only.  N42 owns the shared
``authority-invariants`` runner, seam coverage evaluator, and CI tier.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class GatewayFaultSeedV1:
    id: str
    seed: int
    fault: str
    expected: str


@dataclass(frozen=True, slots=True)
class GatewayInvariantV1:
    id: str
    statement: str
    fixture_ids: tuple[str, ...]


def _load_json(name: str) -> dict[str, object]:
    resource = files("parcel_robot.bridge").joinpath("fixtures", name)
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{name} must contain a JSON object")
    return value


def _exact(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} fields differ from the frozen V1 schema")


def load_gateway_fault_seeds_v1() -> tuple[GatewayFaultSeedV1, ...]:
    document = _load_json("gateway_fault_seeds_v1.json")
    _exact(document, {"schema_version", "scope", "cases"}, "fault seed manifest")
    if document["schema_version"] != 1:
        raise ValueError("unsupported gateway fault seed manifest version")
    cases = document["cases"]
    if not isinstance(cases, list):
        raise TypeError("fault seed cases must be a list")
    result: list[GatewayFaultSeedV1] = []
    for index, raw in enumerate(cases):
        if not isinstance(raw, dict):
            raise TypeError(f"fault seed case {index} must be an object")
        _exact(raw, {"id", "seed", "fault", "expected"}, f"fault seed case {index}")
        case = GatewayFaultSeedV1(**raw)
        if not case.id.startswith("GWF-") or not case.fault or not case.expected:
            raise ValueError(f"fault seed case {index} has invalid identity")
        if isinstance(case.seed, bool) or not isinstance(case.seed, int) or case.seed < 1:
            raise ValueError(f"fault seed case {index} has invalid seed")
        result.append(case)
    if len({case.id for case in result}) != len(result):
        raise ValueError("gateway fault seed IDs must be unique")
    if len({case.seed for case in result}) != len(result):
        raise ValueError("gateway fault numeric seeds must be unique")
    return tuple(result)


def load_gateway_invariants_v1() -> tuple[GatewayInvariantV1, ...]:
    document = _load_json("gateway_invariants_v1.json")
    _exact(
        document,
        {"schema_version", "scope", "owner", "evaluator_owner", "invariants"},
        "gateway invariant manifest",
    )
    if document["schema_version"] != 1:
        raise ValueError("unsupported gateway invariant manifest version")
    if document["owner"] != "N24" or document["evaluator_owner"] != "N42":
        raise ValueError("gateway invariant/evaluator ownership changed")
    raw_invariants = document["invariants"]
    if not isinstance(raw_invariants, list):
        raise TypeError("gateway invariants must be a list")
    fixture_ids = {case.id for case in load_gateway_fault_seeds_v1()}
    result: list[GatewayInvariantV1] = []
    for index, raw in enumerate(raw_invariants):
        if not isinstance(raw, dict):
            raise TypeError(f"gateway invariant {index} must be an object")
        _exact(raw, {"id", "statement", "fixture_ids"}, f"gateway invariant {index}")
        raw_fixtures = raw["fixture_ids"]
        if not isinstance(raw_fixtures, list) or not all(
            isinstance(item, str) for item in raw_fixtures
        ):
            raise TypeError(f"gateway invariant {index} fixture_ids must be strings")
        invariant = GatewayInvariantV1(
            id=str(raw["id"]),
            statement=str(raw["statement"]),
            fixture_ids=tuple(raw_fixtures),
        )
        if not invariant.id.startswith("GWI-") or not invariant.statement:
            raise ValueError(f"gateway invariant {index} has invalid identity")
        if not invariant.fixture_ids or not set(invariant.fixture_ids) <= fixture_ids:
            raise ValueError(f"gateway invariant {invariant.id} has unknown/missing fixtures")
        result.append(invariant)
    if len({invariant.id for invariant in result}) != len(result):
        raise ValueError("gateway invariant IDs must be unique")
    return tuple(result)
