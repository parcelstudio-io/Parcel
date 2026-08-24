"""H8 / S8 — the PRODUCT-PATH probe: a real ``RobotRuntime``'s ``navigate_to``.

Builds the shipping runtime against a no-simulator backend, wires the shipping
:class:`RealtimeToolBroker` to the runtime's OWN doors, and asks the door for a
noun the map has never heard of. Records where the request stops, which layer
stopped it, and whether the navigator's SearchEntity ladder was ever reached.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import yaml

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import VelocityCommand

REPO = Path(__file__).resolve().parents[3]
DEFAULT_NAV_CONFIG = REPO / "configs" / "navigation" / "default.yaml"


class _Backend:
    """The smallest backend a runtime can turn against. No simulator, no socket."""

    name = "h8-fake"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend="h8-fake",
            nearest_obstacle_m=10.0,
        )

    def observe(self) -> SimObservation:
        with self._lock:
            return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _robot_config(tmp: Path) -> Path:
    nav = tmp / "navigation.yaml"
    nav.write_text(DEFAULT_NAV_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp / "robot.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "skills": {"root": str(REPO / "configs" / "skills")},
                "navigation": {"enabled": False, "config": str(nav)},
                "motion": {
                    "backend": "rl",
                    "max_vx": 0.6,
                    "max_vy": 0.4,
                    "max_vyaw": 1.0,
                    "rl": {"enabled": True, "policy_path": ""},
                },
                "memory": {"path": ":memory:"},
                "poses": {},
                "modules": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def probe(tmp: Path, nouns: tuple[str, ...]) -> dict[str, object]:
    from parcel_robot.navigation.goals import (
        admit_navigation_place,
        navigation_directive_from_text,
        semantic_goal_from_directive,
    )
    from parcel_robot.runtime import RobotRuntime

    runtime = RobotRuntime(_robot_config(tmp), _Backend(), language_model=None)
    regions, objects = runtime._realtime_scene_vocabulary()
    places = runtime._realtime_places()
    rows: dict[str, object] = {
        "scene_region_vocabulary": list(regions),
        "scene_object_vocabulary": list(objects),
        "offer_places": list(places),
        "nouns": {},
    }
    for noun in nouns:
        directive = f"go to {noun}"
        admission = runtime._place_admission(directive)
        goal = None
        try:
            goal = semantic_goal_from_directive(
                directive, region_labels=regions, object_labels=objects
            )
        except ValueError:
            pass
        door: dict[str, object]
        try:
            reply = runtime._realtime_navigate(noun)
            door = {"raised": None, "reply": reply}
        except Exception as error:  # noqa: BLE001 — the probe records the failure
            door = {"raised": type(error).__name__, "reply": str(error)}
        rows["nouns"][noun] = {  # type: ignore[index]
            "directive": directive,
            "router_normalized": navigation_directive_from_text(directive),
            "admission": {
                "admitted": admission.admitted,
                "reason": admission.reason,
                "query": admission.query,
                "alternatives": list(admission.alternatives),
                "fact": admission.fact() if not admission.admitted else "",
            },
            "compiled_goal": (
                None
                if goal is None
                else {
                    "query": goal.query,
                    "kind": goal.kind,
                    "terminal_relation": goal.terminal_relation,
                    "place_class": getattr(goal, "place_class", ""),
                }
            ),
            "door": door,
        }
    # The explicit-search escape hatch the admission gate already has.
    for phrase in ("look for city books", "find the city books"):
        rows.setdefault("explicit_search", {})[phrase] = {  # type: ignore[union-attr]
            "normalized": navigation_directive_from_text(phrase),
            "admitted": admit_navigation_place(
                phrase, tuple(regions) + tuple(objects), offer=places
            ).admitted,
            "reason": admit_navigation_place(
                phrase, tuple(regions) + tuple(objects), offer=places
            ).reason,
        }
    runtime.close()
    return rows


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("results/runtime_probe.json")
    tmp = Path(argv[2]) if len(argv) > 2 else Path("/tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    payload = probe(tmp, ("city books", "narnia", "bench", "the sidewalk"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
