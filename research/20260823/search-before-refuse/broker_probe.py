"""H8 — the door probe: what the hosted ``navigate_to`` door does with an
unknown noun, in each ``unknown_place`` mode, plus the S8 product-path check.

Run twice: once at HEAD (baseline, ``refuse``/``ask`` only) and once after the
seam lands, so the two ``refuse``/``ask`` captures can be compared byte for byte.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from parcel_robot.realtime import tool_broker as TB

CITY_PLACES = ("crosswalk", "sidewalk", "planter", "bench", "lamppost", "tree", "door")
UNKNOWN_NOUNS = ("city books", "narnia", "the bookshop on the corner")
KNOWN_NOUN = "bench"
JUNK_NOUN = "with owner"


class _Doors:
    """A wired host: every door answers, ``navigate`` records what it was given."""

    def __init__(self, *, navigate_raises: str = "") -> None:
        self.navigate_calls: list[tuple[Any, ...]] = []
        self.navigate_raises = navigate_raises

    def validate(self, call: Any) -> Any:
        return TB.ToolResult(name=call.name, accepted=True, message="admitted")

    def status(self) -> dict[str, object]:
        return {"state": "idle"}

    def recall(self, query: str) -> str:
        return ""

    def gesture(self, name: str, intensity: float) -> str:
        return "ok"

    def pose(self, name: str) -> str:
        return "ok"

    def navigate(self, place: str, relation: str = "", **kwargs: object) -> str:
        self.navigate_calls.append((place, relation, dict(sorted(kwargs.items()))))
        # The runtime's R20 gate (``RobotRuntime._place_admission``) refuses a
        # noun its vocabulary cannot resolve and raises ``PlaceAdmission.fact()``.
        # Reproduced here so the capture shows what the model reads end to end.
        if self.navigate_raises and place.strip().lower() not in CITY_PLACES:
            raise ValueError(self.navigate_raises)
        return f"Okay—I'll navigate toward {place} safely."

    def places(self) -> tuple[str, ...]:
        return CITY_PLACES


def _door_kwargs(doors: _Doors) -> dict[str, object]:
    return {
        "validate": doors.validate,
        "status": doors.status,
        "recall": doors.recall,
        "gesture": doors.gesture,
        "pose": doors.pose,
        "navigate": doors.navigate,
        "places": doors.places,
    }


def _broker(mode: str, doors: _Doors) -> Any:
    kwargs: dict[str, object] = {"unknown_place": mode}
    return TB.RealtimeToolBroker(TB.ToolDoors(**_door_kwargs(doors)), **kwargs)


#: The owner's live refusal, verbatim (research/.../DESIGN.md "Owner's report").
OWNER_REFUSAL_FACT = (
    "the robot's map has no place called 'city books'; the places it does know "
    "nearby are the crosswalk, the sidewalk and the planter; ask the owner which "
    "of those they mean, or which real place they want"
)


def capture(modes: tuple[str, ...]) -> dict[str, object]:
    rows: dict[str, object] = {}
    for mode in modes:
        per_mode: dict[str, object] = {}
        for noun in (*UNKNOWN_NOUNS, KNOWN_NOUN, JUNK_NOUN):
            # The door raises exactly what the runtime's R20 gate raises, so the
            # capture shows what the model reads end to end.
            doors = _Doors(navigate_raises=OWNER_REFUSAL_FACT)
            broker = _broker(mode, doors)
            raw = broker.handle(
                name="navigate_to",
                call_id=f"h8-{mode}-{noun}",
                arguments=json.dumps({"place": noun}),
            )
            result = json.loads(raw)
            per_mode[noun] = {
                "result": _plain(result),
                "navigate_calls": [list(c[:2]) + [c[2]] for c in doors.navigate_calls],
                "snapshot": {
                    key: value
                    for key, value in broker.snapshot().items()
                    if key
                    in {
                        "executed",
                        "rejected",
                        "dropped",
                        "unknown_place_mode",
                        "unknown_place_asks",
                        "searches",
                        "search_found",
                        "search_not_found",
                    }
                },
            }
        rows[mode] = per_mode
    return rows


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("results/broker_capture.json")
    modes = tuple(argv[2].split(",")) if len(argv) > 2 else ("refuse", "ask")
    payload = capture(modes)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
